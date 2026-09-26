"""What one round is sent, and the numbers it came back with.

Part of Session (ralph_session.py), kept apart so each file stays small enough
for one round to read whole: the file list for the item, the documents it may
consult, the command line, and the per-round telemetry.
"""

import ast
import os
import re
import time

import status
from ralph_common import LOCATE, SCAN, read_text, say
from ralph_locate import locate
from ralph_scan import baseline, scan
from ralph_prompts import compose_round_prompt, design_guide
from ralph_rounds import SYMBOL, build_round_command, files_for_task, run_round
from ralph_tools import FOUND_FILE, SKILLS_FILE


# How long an answer to a RESEARCH:, FIND: or DOCS: request keeps being sent
# with every round. Long enough for the round that asked, and the one after it.
ANSWER_MINUTES = 20


def recently_written(path, minutes=ANSWER_MINUTES):
    try:
        return time.time() - os.path.getmtime(path) < minutes * 60
    except OSError:
        return False


def attempt_temperature(attempt, code, brainstorm, step=0.25):
    """Warmer with each try at the same item, up to the brainstorm setting.

    Repeated sampling with a verifier -- the tests and the reviewer here --
    beats one careful attempt by a wide margin (Brown et al., "Large Language
    Monkeys", 2024), but only if the attempts differ. At one temperature a
    retry mostly writes the same rejected change again.
    """
    return round(min(max(code, brainstorm), code + step * max(0, attempt - 1)), 2)


# The reviewers read one round's diff and nothing else. On 2026-09-24 about
# half the changes they sent back were sound: a second read "found" imports
# missing that sat above the lines shown, a round adding the test its item
# asked for was turned down for not changing a function an earlier round had
# already changed, and another for not changing one that already did what
# the item wanted. So they are told what the checks have settled, and shown
# the code the item names as it stands now.
SETTLED = ("\nAlready settled by the automatic checks, before any reader: it parses, it starts "
           "or imports cleanly, and any tests pass.%s The diff shows only the lines that "
           "changed and a few around them, so a name it uses without showing where it comes "
           "from is defined or imported in lines not shown -- that is not a fault.\n")
LINTED = " pyflakes read every file whole after the change and found no name it left undefined."
NAMED_CODE_CHARS = 6000


def named_code(task, files, limit=NAMED_CODE_CHARS):
    """[(file, name, source)]: what the item names in backticks, as it is now.

    `f` finds a function or class, `Class.method` a method. Test files are
    looked in last, and each name is shown once. Stops short of `limit`
    characters, so a whole big class never crowds out the diff.
    """
    names = []
    for symbol in SYMBOL.findall(task or ""):
        if symbol not in names:
            names.append(symbol)
    found, used = [], 0
    for path in sorted(files, key=lambda p: os.path.basename(p).startswith("test_")):
        if not names or not path.endswith(".py") or not os.path.isfile(path):
            continue
        body = read_text(path)
        try:
            tree = ast.parse(body)
        except (SyntaxError, ValueError):
            continue
        lines = body.splitlines(keepends=True)
        for name in list(names):
            node = _definition(tree.body, name.split("."))
            if node is None:
                continue
            names.remove(name)
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            source = "".join(lines[start - 1:node.end_lineno])
            if used + len(source) <= limit:
                found.append((path, name, source))
                used += len(source)
    return found


def _definition(nodes, parts):
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name == parts[0]:
            if len(parts) == 1:
                return node
            return _definition(node.body, parts[1:]) if isinstance(node, ast.ClassDef) else None
    return None


def review_context(task, files, linted):
    """What the reviewers are told beyond the diff (see SETTLED)."""
    text = SETTLED % (LINTED if linted else "")
    shown = named_code(task, files)
    if shown:
        text += ("\nFor reference, the code the item names as it stands after this change. "
                 "Earlier rounds on the item may already have done part of it: whether the "
                 "item is done is judged by this code, and faults are looked for in the diff.\n")
        for path, name, source in shown:
            text += "\n%s, `%s`:\n\n%s\n" % (os.path.basename(path), name, source.rstrip())
    return text


class SendMixin:

    def send_round(self, task, phase="code"):
        """Build the prompt and the file list, run aider, record the numbers.

        A test round (ralph_testfirst.py) gets the item's code to read and only
        its test file to edit.
        """
        round_prompt = compose_round_prompt(self.workspace, self.prompt_path, self.broken,
                                            cut_off=self.was_cut_off, task=task,
                                            last_failure_kind=self.last_failure_kind,
                                            phase_note=self.phase_note(task, phase))
        # Only the files this item names, so a multi-module project does not
        # pay for all of itself on every round.
        self.set_temperature(attempt_temperature(self.rounds_on_task, self.temp_code,
                                                 self.temp_brainstorm))
        # What is already wrong, so only what this round adds is held against it.
        self.scan_before = baseline(self.edit_files) if SCAN else {}
        round_files = files_for_task(task, self.edit_files)
        if not round_files and LOCATE and self.ask and len(self.edit_files) > 1:
            # It names nothing that can be found. Ask which files, once per item.
            if task not in self.located:
                status.phase("locating", task)
                self.located[task] = locate(task, self.edit_files, self.ask)
                if self.located[task]:
                    self.note("  located: %s" % ", ".join(
                        os.path.basename(f) for f in self.located[task]))
            round_files = list(self.located[task])
        if len(round_files) < len(self.edit_files):
            approx_tokens = 0
            for path in round_files:
                try:
                    approx_tokens += os.path.getsize(path) // 4
                except OSError:
                    pass
            say("    sending %d of %d files (~%d tokens)"
                % (len(round_files), len(self.edit_files), approx_tokens))
        # A document the item names by file (SKILLS.md, KNOWLEDGE.md) goes in
        # editable; everything else it may want to consult goes in read-only.
        docs = [os.path.join(self.workspace, name) for name in
                sorted(set(re.findall(r"\b([\w-]+\.md)\b", task)))]
        docs = [d for d in docs if os.path.isfile(d) and d != self.notes_path]
        round_files = round_files + docs
        study = []
        if phase == "test":
            target = os.path.join(self.workspace, self.test_target(task))
            study = [f for f in round_files if f != target]
            round_files = [target] if os.path.isfile(target) else []
        # Answers go stale. Research from an hour ago, or a code search for an
        # item three rounds back, is 2,000 tokens of the window spent on
        # something nobody asked about any more -- and rounds were reaching
        # 29,000 of 32,768, which loses the room the reply needs and makes
        # every request cost more memory in the engine.
        answers = [p for p in (self.research_path, os.path.join(self.workspace, FOUND_FILE))
                   if recently_written(p)]
        reads = study + [p for p in (answers + [self.conventions, design_guide(task),
                                        os.path.join(self.workspace, SKILLS_FILE)])
                 if p and os.path.isfile(p) and p not in docs]
        if self.lean:
            # The last prompt for this item was refused as too big to read.
            round_files, reads = round_files[:1], reads[:1]
            say("    sending less after a refused prompt: %d file(s), %d to read"
                % (len(round_files), len(reads)))
        cmd = build_round_command(self.base_cmd, round_prompt, self.notes_path,
                                  round_files, reads)
        started = time.time()
        free_before = self.headroom()
        result = run_round(cmd, self.workspace, self.child_env, self.iteration_timeout,
                           label="round %d: %s" % (self.rounds, task[:50]))
        spent = max(time.time() - started, 0.001)
        status.update(rounds=self.rounds, last_round_seconds=round(spent),
                      tok_per_sec=round(result.got / spent, 1) if result.got else None,
                      last_in=result.sent, last_out=result.got)
        self.pace.append((spent, result.sent, result.got))
        self.count_tokens(result)
        if result.got:
            self.engine_streak = 0      # it answered; the run is alive
        if result.symptom != "context":
            self.was_cut_off = False    # it got to the end of what it wanted to say
        if result.failed:
            self.edit_misses += 1
            self.note("  %d edit(s) did not match the file." % result.failed)
        elif result.applied:
            self.edit_misses = 0
        if result.got:
            self.note("  %.0fs, %s tokens in / %s out, %.0f tok/sec"
                      % (spent, "{:,}".format(result.sent), "{:,}".format(result.got),
                         result.got / spent))
        # Not fatal, but not nothing: an engine that needs retrying to answer
        # is an engine on its way out, and this is the only warning before it
        # stops answering at all.
        if result.shrugged_off:
            self.wobbles += result.shrugged_off
            self.note("  %d engine error(s) retried through - it is wobbling."
                      % result.shrugged_off)
        free_after = self.headroom()
        if free_after is not None:
            status.update(vram_free=free_after)
        if free_before is not None and free_after is not None:
            self.note("  VRAM free %d -> %d MiB" % (free_before, free_after))
            if min(free_before, free_after) < 1024:
                self.note("  Headroom is under 1 GB. This is where the engine dies -")
                self.note("  lower LC_CONTEXT, or close whatever else wants the card.")
        return result

    def scan_round(self, diff):
        """The no-token checks on this round: [(kind, message)]. See ralph_scan.py."""
        if not SCAN:
            return []
        try:
            return scan(self.edit_files, diff, self.current_task,
                        getattr(self, "scan_before", {}) or {})
        except Exception as exc:
            self.note("  the automatic checks failed to run: %s" % exc)
            return []

    def second_opinion(self, task, diff, notes):
        """The reviewer's verdict, told what the automatic checks noticed and
        settled, and shown the code the item names (review_context)."""
        linted = bool(SCAN) and (getattr(self, "scan_before", {}) or {}).get("lint") is not None
        extra = {"context": review_context(task, self.edit_files, linted)
                 + getattr(self, "review_note", "")}
        if notes:
            extra["notes"] = notes
        try:
            return self.review(task, diff, **extra)
        except TypeError:
            pass
        return self.review(task, diff)

