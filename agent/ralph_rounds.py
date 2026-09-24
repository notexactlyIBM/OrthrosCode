"""Running one aider round and reading what happened, plus research and the diff
a reviewer is shown."""

import collections
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import status
from ralph_common import (PLAN_FILE, RESEARCH_AUTO, RESEARCH_FILE,
    ROUND_FILE, TRANSCRIPT_CAP, TRANSCRIPT_FILE, read_text, say, write_text)
from ralph_tasks import PLAN_HEADER
from ralph_prompts import compose_refill_prompt, design_guide
from ralph_tools import LESSONS_FILE

# Written by Orthros after each turn: how the agent in this folder performed.
FIELD_REPORT_FILE = "FIELD_REPORT.md"


DIFF_BUDGET = 14000      # characters of diff a review is shown, ~3,500 tokens


def round_diff(workspace, edit_files, budget=DIFF_BUDGET):
    """What this round changed in the source, as a diff. '' if unknown.

    Everything since the last commit, and LocalCoder commits after every round
    it keeps, so that is this round's work exactly. New files have no diff
    against the last commit, so they are shown whole.
    """
    git = shutil.which("git")
    if not git:
        return ""
    rel = [os.path.relpath(f, workspace) for f in edit_files if os.path.isfile(f)]
    try:
        changed = subprocess.run([git, "-C", workspace, "diff", "HEAD", "--unified=4",
                                  "--"] + rel, capture_output=True, text=True,
                                 timeout=60, encoding="utf-8", errors="replace").stdout or ""
        fresh = subprocess.run([git, "-C", workspace, "ls-files", "--others",
                                "--exclude-standard", "--", "*.py"],
                               capture_output=True, text=True, timeout=60,
                               encoding="utf-8", errors="replace").stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for name in fresh.split():
        changed += "\n\nNEW FILE %s:\n%s" % (name, read_text(os.path.join(workspace, name)))
    if len(changed) > budget:
        changed = changed[:budget] + ("\n\n[... diff cut here at %d characters -- the "
                                      "rest was not shown to you ...]" % budget)
    return changed


def run_research(workspace, query, timeout=120):
    """Look something up and leave it in RESEARCH.md. Returns True if written."""
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(workspace, RESEARCH_FILE)
    try:
        proc = subprocess.run(
            [os.path.join(here, "venv", "Scripts", "python.exe"),
             os.path.join(here, "research.py"), "--query", query, "--out", out_path],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and os.path.isfile(out_path)


def project_stack(files):
    """The main third-party library this project is built on, or ''.

    So a search about "weapon selection" becomes a search about weapon
    selection *in the thing actually being used*, without LocalCoder knowing
    anything about the project. Read from its imports: the non-standard
    module imported most often is almost always the framework.
    """
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    local = {os.path.splitext(os.path.basename(f))[0] for f in files}
    counts = {}
    for path in files:
        for mod in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)",
                              read_text(path), re.MULTILINE):
            if mod in stdlib or mod in local or mod == "__future__":
                continue
            counts[mod] = counts.get(mod, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def research_before(workspace, topic, edit_files):
    """Read up on a milestone before planning it. Returns the query, or ''.

    The web tool was here from the start and in the whole history of this
    project it was used zero times. It waited for the model to write
    `RESEARCH: <question>`, which means waiting for a small model to admit it
    does not know something -- and it never does. It guesses, confidently.

    So the loop no longer waits to be asked. Breaking a milestone into steps
    is exactly the moment reference material helps -- how a charge-up shot is
    usually done, what a library offers for it -- and looking it up costs
    nothing but a few seconds, because the search is free.
    """
    stack = project_stack(edit_files)
    lang = "python" if any(f.endswith(".py") for f in edit_files) else ""
    query = " ".join(p for p in (lang, stack, topic, "how to implement") if p)
    return query if run_research(workspace, query) else ""


def refill_list(base_cmd, workspace, child_env, notes_path, edit_files, timeout,
                refills=1):
    """Ask for more work when the list runs dry but the clock has not.

    Without this the session ends the moment the last box is ticked, however
    much budget is left -- ask for two hours against fifteen minutes of list
    and you get fifteen minutes.

    Where the work comes from is the task list's own doing: the standing
    sections at the bottom of it, taken one per refill. Failing those, it falls
    back to reading the code and doubting what has already been ticked.

    Only the notes file is editable here. A review round that starts rewriting
    the game is a review round that has misunderstood the question.

    Returns (RoundResult, label, mode, milestone).
    """
    prompt, source, mode, milestone = compose_refill_prompt(notes_path, refills)
    status.phase("planning", "%s: %s" % (mode, source))
    path = os.path.join(workspace, ROUND_FILE)
    write_text(path, prompt)
    plan_path = os.path.join(os.path.dirname(notes_path), PLAN_FILE)
    # A planning round writes the plan; every other round writes the list.
    # Only ever one editable file, so there is no question where edits land.
    target = plan_path if mode == "plan" else notes_path
    if mode == "plan" and not os.path.isfile(plan_path):
        write_text(plan_path, PLAN_HEADER)
    cmd = list(base_cmd) + ["--message-file", path, "--yes-always", "--file", target]
    # Only the source. Not BRIEF.md -- the section this round is working from
    # is already quoted into the prompt above, and sending the file too would
    # send it twice and the other sections along with it. Not DONE.md either:
    # it grows without limit, and the recent finished items kept in the task
    # list are what the review actually checks against the code. Both files
    # stay readable; neither is worth a token on every refill.
    # A budgeted slice of the source, not all of it -- see files_for_refill.
    reads = files_for_refill("%s %s" % (milestone or "", source), edit_files)
    if mode == "plan":
        # The planner needs to see what is already on the list so it does not
        # propose ground the current batch already covers.
        reads.append(notes_path)
    # Read up before breaking a milestone down, rather than hoping to be asked.
    guide = design_guide(milestone, source)
    if guide and mode != "plan":
        reads.append(guide)
    if mode == "decompose" and milestone and RESEARCH_AUTO:
        status.phase("researching", milestone)
        looked_up = research_before(workspace, milestone, edit_files)
        if looked_up:
            say("    read up first: %s" % looked_up[:60])
            reads.append(os.path.join(workspace, RESEARCH_FILE))
    # How the agent being worked on actually did in its last turns, and the
    # mistakes rounds keep making: the evidence a plan should start from.
    reads += [os.path.join(workspace, name) for name in (FIELD_REPORT_FILE, LESSONS_FILE, "KNOWLEDGE.md")]
    for extra in reads:
        if extra and os.path.isfile(extra):
            cmd += ["--read", extra]          # readable, not writable
    result = run_round(cmd, workspace, child_env, timeout,
                       label="refill %d (%s): %s" % (refills, mode, source))
    return result, source, mode, milestone


SYMBOL = re.compile(r"`([A-Za-z_][\w.]*)`")


FILE_MENTION = re.compile(r"\b([\w-]+\.(?:py|js|mjs|ts|tsx|jsx|html|css))\b")

# Tokens of source a round may carry when its item names nothing that can be
# found. Under it, everything is sent; over it, nothing is, and the repo map
# plus aider's own offer to add the files the model asks for have to do.
FALLBACK_TOKENS = 12000


def files_for_task(task_text, edit_files):
    """Send only the files the item actually names.

    Every file listed goes in on every round, so a project grows until one
    round no longer fits and the whole approach stops working. Items here name
    their target -- ``In `Terrain.render`, ...`` -- so the file holding that
    symbol is usually the only one needed, and the rest is dead weight.

    A file named outright ("in research.py") counts too: that is how an item
    about a function that does not exist yet says where it goes.

    Naming nothing findable used to mean "send everything". For a project
    bigger than the window that is a round certain to fail before the model
    says a word, so past FALLBACK_TOKENS it now sends nothing instead.
    """
    if len(edit_files) < 2:
        return list(edit_files)
    symbols = SYMBOL.findall(task_text)
    names = {m.split(".")[0] for m in symbols}
    # For `Class.method`, the method's own name too. LocalCoder moves big
    # methods into modules of their own, leaving a one-line stub in the class
    # -- so the code the item is about may live in <class>_<method>.py.
    methods = {m.split(".")[-1] for m in symbols if "." in m}
    mentioned = {m.lower() for m in FILE_MENTION.findall(task_text)}
    defines = re.compile(r"^\s*(?:class|def|async\s+def)\s+(%s)\b"
                         % "|".join(re.escape(n) for n in names), re.MULTILINE) if names else None
    top_level = re.compile(r"^def\s+(%s)\(" % "|".join(re.escape(m) for m in methods),
                           re.MULTILINE) if methods else None
    wanted = []
    for path in edit_files:
        if os.path.basename(path).lower() in mentioned:
            wanted.append(path)
            continue
        if not names:
            continue
        body = read_text(path)
        if defines.search(body) or (top_level and top_level.search(body)):
            wanted.append(path)
    if wanted:
        return wanted
    total = sum(os.path.getsize(p) for p in edit_files if os.path.isfile(p)) // 4
    return list(edit_files) if total <= FALLBACK_TOKENS else []


REFILL_SOURCE_BUDGET = 8000   # tokens of source a planning round may carry


def files_for_refill(topic, edit_files, budget=REFILL_SOURCE_BUDGET):
    """Source to show a round that plans rather than edits. Within a budget.

    Refill rounds used to get every source file. With one file that was
    affordable; after the project was split into modules it meant the whole
    codebase, and a refill's prompt reached 29,600 of 32,768 tokens before the
    model said a word. Every refill then failed the same way, "moving on to
    the next brief" moved to one with the same bloated input, and on
    2026-08-14 that spun for 45 minutes without adding an item.

    Planning does not need every line -- the repo map gives it the shape of
    the whole project. It needs the modules this milestone is about, if the
    text names any, and then whatever else fits, smallest first.
    """
    if FALLBACK_TOKENS == 0:
        return []
    named = files_for_task(topic or "", edit_files) if topic else []
    if len(named) == len(edit_files):
        named = []                       # named nothing recognisable
    # What the milestone names always goes in -- a working round sends that
    # module whole anyway. The budget only limits the extras around it.
    chosen = list(named)
    spent = sum(os.path.getsize(p) // 4 for p in chosen)
    for path in sorted((f for f in edit_files if f not in named),
                       key=lambda f: os.path.getsize(f)):
        cost = os.path.getsize(path) // 4
        if spent + cost > budget:
            continue
        chosen.append(path)
        spent += cost
    return chosen


def build_round_command(base_cmd, prompt_path, notes_path, edit_files, read_files):
    cmd = list(base_cmd)
    cmd += ["--message-file", prompt_path, "--yes-always"]
    for path in [notes_path] + list(edit_files):
        if path and os.path.isfile(path):
            cmd += ["--file", path]
    for path in read_files:
        if path and os.path.isfile(path):
            cmd += ["--read", path]
    return cmd


OUT_OF_ROOM = "hit a token limit"


# aider says this when the model's SEARCH block does not match the file. On a
# small model it is the most common way a round achieves nothing at all.
EDIT_FAILED = "search/replace block failed to match"


APPLIED = "applied edit"


# The engine falling over does not announce itself the same way twice, and only
# one of these phrasings was ever being looked for. The rest read as an ordinary
# empty round, which is how three sessions in a row came to be logged as "it
# could not think of anything else" when LM Studio had in fact died. Every
# string here is quoted from this rig's own console:
#
#   no models loaded ............ server up, nothing resident
#   bad allocation .............. llama.cpp could not get the memory it wanted
#   predict stream returned ..... engine died part-way through an answer
#   predict request failed ...... engine already gone when the request landed
#   startup was aborted ......... reload attempted before teardown finished
#   fetch failed / refused ...... LM Studio's own API server went down with it
ENGINE_DEAD = (
    "no models loaded",
    "bad allocation",
    "predict stream returned an error",
    "predict request failed",
    "engine protocol startup was aborted",
    "fetch failed",
    "connection refused",
    "apiconnectionerror",
    # A wedged engine says none of the above. It stays loaded, keeps the port
    # open, and answers nothing -- so `lms ps` still lists it and the watchdog
    # sees a healthy model. What it produces is this, and until 2026-08-08 the
    # loop read it as "the round did nothing": five rounds and twelve minutes
    # burned on a dead engine, and two perfectly good items parked as though
    # they were the problem.
    "internalservererror",
    "servers are down or overloaded",
    "connection error",
    "openaiexception - timed out",
)


# The prompt was bigger than the window and was never processed. LM Studio
# answers 400, and aider words that as `litellm.APIConnectionError` -- which
# is in ENGINE_DEAD. So on 2026-09-23 a prompt 190 tokens too big was taken
# for a dead engine five times over: reload, resend the same prompt, and the
# turn ended at "Five rounds in a row lost to the engine". Checked after the
# dead-engine phrases and overriding them, because the connection-error line
# comes first. The last is Orthros's guard declining to send one at all.
TOO_BIG = (
    "exceeds the available context size",
    "exceed_context_size_error",
    "orthros guard: prompt too big",
)


# aider prints e.g. "Tokens: 8.2k sent, 4.2k received." once per exchange.
TOKEN_LINE = re.compile(
    r"tokens:\s*([\d,.]+)\s*([km]?)\s*sent,\s*([\d,.]+)\s*([km]?)\s*received", re.I)


# When aider reports hitting a limit it also prints the arithmetic:
#   Total tokens: ~29,671 of 32,768 -- possibly exhausted context window!
# Which of the two limits was actually hit matters enormously, and the
# message alone does not say. See `crowded` below.
TOTAL_LINE = re.compile(r"total tokens:\s*~?([\d,]+)\s*of\s*([\d,]+)", re.I)


INPUT_LINE = re.compile(r"input tokens:\s*~?([\d,]+)\s*of\s*([\d,]+)", re.I)


# What one round of aider did, in the only terms we can observe from outside.
# `tail` is the last of its output, kept so a round that achieved nothing can
# say why in the log instead of leaving it to the console nobody was watching.
# `refused`: the prompt was too big to be read at all -- see TOO_BIG.
RoundResult = collections.namedtuple(
    "RoundResult",
    "ran symptom sent got applied failed tail shrugged_off crowded overstuffed refused",
    defaults=(False,))


NOTHING = RoundResult(False, "", 0, 0, 0, 0, (), 0, False, False)


# How full the window has to be before an over-long reply is the window's
# fault. Below this, the reply was cut off by our own max_tokens ceiling and
# cutting it further makes the next round worse, not better.
CROWDED_AT = 0.85


# Above this share of the window taken by the prompt alone, neither lever
# works. Growing the reply ceiling cannot help -- there is no room to grow
# into -- and shrinking it only truncates the answer sooner. Measured
# 2026-08-10: input sat at 21,000-23,600 of 32,768 for a whole session while
# the ceiling oscillated 8192 -> 4096 -> 6096 -> 3048 -> 5048 -> 3000, each
# swing costing a round, because every reply looked too long and the window
# looked nearly full and both readings were true. The prompt was the problem.
CROWDED_INPUT = 0.6


def _scale(number, suffix):
    return int(float(number.replace(",", "")) * {"k": 1000, "m": 1000000}.get(suffix.lower(), 1))


def open_transcript(workspace, label, cmd):
    """Append-and-flush handle on aider's raw output. None if it cannot open.

    Rotated rather than truncated: the interesting session is usually the one
    that just died, and the one before it is what you compare against.
    """
    path = os.path.join(workspace, TRANSCRIPT_FILE)
    try:
        if os.path.getsize(path) > TRANSCRIPT_CAP:
            old = path + ".1"
            if os.path.isfile(old):
                os.remove(old)
            os.rename(path, old)
    except OSError:
        pass
    try:
        handle = open(path, "a", encoding="utf-8", errors="replace")
        handle.write("\n\n===== %s | %s =====\n"
                     % (time.strftime("%Y-%m-%d %H:%M:%S"), label))
        handle.write("$ %s\n\n" % subprocess.list2cmdline(cmd))
        handle.flush()
        return handle
    except OSError:
        return None


def run_round(cmd, workspace, child_env, timeout, label="round"):
    """One aider process, one message, then it exits.

    Its output is echoed as it arrives, written to the transcript, *and*
    watched, because every failure that matters here only ever announces itself
    in aider's own text: the reply outgrowing the context window, the engine
    dying underneath it, a diff that would not apply. Returns a RoundResult.
    """
    handle = open_transcript(workspace, label, cmd)
    try:
        proc = subprocess.Popen(
            cmd, cwd=workspace, env=child_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except OSError as exc:
        say("    could not start aider: %s" % exc)
        if handle:
            handle.write("could not start aider: %s\n" % exc)
            handle.close()
        return NOTHING._replace(tail=("could not start aider: %s" % exc,))

    # The timer has to be its own thread. Checking the clock inside the read
    # loop only works while output keeps arriving, and the round most in need
    # of killing is the one that has gone silent -- a wedged model prints
    # nothing at all, so the check would never come round again.
    timed_out = []

    def give_up():
        timed_out.append(True)
        say("    this round passed %d seconds with nothing to show - stopping it" % timeout)
        try:
            proc.kill()
        except OSError:
            pass

    timer = threading.Timer(timeout, give_up)
    timer.daemon = True
    timer.start()

    symptom = ""
    sent = received = 0
    applied = failed = 0
    shrugged_off = 0   # engine errors aider retried through and survived
    crowded = False    # was the WINDOW full, or just our own reply ceiling?
    overstuffed = False  # or was the PROMPT too big for either to matter?
    refused = False    # or too big to be read at all?
    # Only the tail is kept in memory. The whole thing is on disk in the
    # transcript; this is what gets quoted into the summary log.
    tail = collections.deque(maxlen=40)
    ran = False
    try:
        for line in proc.stdout:
            stripped = line.rstrip()
            print(stripped, flush=True)
            if handle:
                handle.write(line if line.endswith("\n") else line + "\n")
                handle.flush()     # a crashed run must still leave the reason
            if stripped.strip():
                tail.append(stripped)
            low = line.lower()
            if OUT_OF_ROOM in low:
                symptom = "context"
            room = TOTAL_LINE.search(line)
            if room:
                used = int(room.group(1).replace(",", ""))
                window = int(room.group(2).replace(",", "")) or 1
                crowded = used >= window * CROWDED_AT
            fat = INPUT_LINE.search(line)
            if fat:
                sent_in = int(fat.group(1).replace(",", ""))
                window = int(fat.group(2).replace(",", "")) or 1
                overstuffed = sent_in >= window * CROWDED_INPUT
            if not room and not fat and not symptom \
                    and any(dead in low for dead in ENGINE_DEAD):
                symptom = "enginedied"
            if any(big in low for big in TOO_BIG):
                symptom, refused, overstuffed, crowded = "context", True, True, True
            if EDIT_FAILED in low:
                failed += 1
            elif low.startswith(APPLIED) or (" " + APPLIED) in low:
                applied += 1
            hit = TOKEN_LINE.search(line)
            if hit:
                # A round can talk to the model more than once; count the lot.
                sent += _scale(hit.group(1), hit.group(2))
                received += _scale(hit.group(3), hit.group(4))
                # aider retries, and it often wins. A token line means the
                # model answered, so whatever error came before it was
                # survived, not fatal -- clear it. Without this, one retried
                # blip marked the whole round as an engine death and sent the
                # loop off to reload a model that had never gone anywhere.
                # Measured on the first live run: a round that applied two
                # edits, with VRAM unchanged, reported as a crash.
                if symptom == "enginedied":
                    symptom = ""
                    shrugged_off += 1
                elif refused:
                    # A later exchange fitted -- aider dropped what it had added.
                    symptom, refused, overstuffed = "", False, False
        proc.wait(timeout=30)
        ran = not timed_out
        if not symptom and proc.returncode not in (0, None) and sent == 0 and applied == 0:
            symptom = "crashed"
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass
    finally:
        timer.cancel()
        try:
            proc.stdout.close()
        except (OSError, AttributeError):
            pass
        # Ctrl+C, a dashboard force-stop, or a bug above must not leave aider
        # running on its own, still editing files and holding the model.
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if handle:
            handle.write("\n----- %s: %s%s -----\n"
                         % ("finished" if ran else "did not finish",
                            symptom or "no symptom seen",
                            ", %d engine error(s) retried through" % shrugged_off
                            if shrugged_off else ""))
            handle.close()
    return RoundResult(ran, symptom, sent, received, applied, failed,
                       tuple(tail), shrugged_off, crowded, overstuffed, refused)
