"""Test first, then code: an item's "Done when" made into a test that runs.

Every item ends with `Done when:` and a check anyone can make. Until
2026-09-26 that check was read by one model and judged by another, and on
2026-09-24 about 40% of the reviewer's rejections were wrong -- mostly for
want of context a diff does not show. A test that passes needs no context
(ORTHROSCODE-IMPROVEMENTS.md, 1).

So an item that a test could check gets two kinds of round:

1. The test round writes one unittest for the `Done when:`, and nothing else.
   The loop runs it: it must fail, or error because what it tests does not
   exist yet. A test that already passes tests nothing.
2. Code rounds then make it pass. The test is put back in the tree at the
   start of each, restored if the round changed it, and runs with every other
   test in the automatic checks.

The test is never committed on its own. A failing test in the history would
mark the project broken for every round after it, and an item parked with its
test unpassed would leave that test failing for good. It goes into the history
with the change that makes it pass, or not at all.
"""

import ast
import os
import re
import subprocess

from ralph_checks import _import_env, code_fingerprint, find_project_python
from ralph_common import _env_flag, _env_int, read_text, write_text

TEST_FIRST = _env_flag("LC_RALPH_TEST_FIRST", True)
TEST_TRIES = _env_int("LC_RALPH_TEST_TRIES", 2)   # failed test rounds before coding without

DONE_WHEN = re.compile(r"Done when:\s*(.+)$", re.I)
NAMED = re.compile(r"`([^`]+)`")
CHECKABLE = re.compile(r"\b(returns?|raises?|prints?|equals?|is|are|==|tests?|passes|finds?)\b",
                       re.I)
CODE_NAME = re.compile(r"^[A-Za-z_][\w.]*(\(\))?$")
PROSE = (".md", ".cmd", ".bat", ".html", ".txt", ".json", ".toml", ".cfg")
FILE_NAMED = re.compile(r"\b([\w-]+\.py)\b")
# What a test of something not written yet dies of. Any other error means the
# test itself is broken.
MISSING_YET = re.compile(r"\b(ImportError|ModuleNotFoundError|AttributeError|NameError)\b")


def acceptance(task_text):
    """The item's `Done when:` check, if a test could state it. Else ''."""
    match = DONE_WHEN.search(task_text or "")
    if not match:
        return ""
    check = match.group(1).strip()
    # Something code-shaped to test: a .py file, or a name like `add` or
    # `Class.method`. An item about SKILLS.md or config.cmd has no test to write.
    names = NAMED.findall(task_text) + FILE_NAMED.findall(task_text)
    code = [n for n in names if n.endswith(".py")
            or (CODE_NAME.match(n) and not n.lower().endswith(PROSE))]
    if not code or not CHECKABLE.search(check):
        return ""
    return check


def test_file_for(task_text, source_files):
    """Where the item's test goes: a test file the item names, else
    test_<first source file it is about>.py. '' if neither."""
    named = [n for n in FILE_NAMED.findall(task_text or "") if n.startswith("test_")]
    if named:
        return named[0]
    for path in source_files:
        base = os.path.basename(path)
        if base.endswith(".py") and not base.startswith("test_"):
            return "test_" + base
    return ""


def test_files(workspace):
    """The top-level test_*.py files, as test_check finds them."""
    try:
        return sorted(n for n in os.listdir(workspace)
                      if n.startswith("test_") and n.endswith(".py"))
    except OSError:
        return []


def _methods(text):
    """{'Class.test_x': source of the method} for one test file. {} if it does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    found = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and item.name.startswith("test"):
                    found["%s.%s" % (node.name, item.name)] = ast.get_source_segment(text, item)
    return found


def snapshot(workspace):
    """{test file: its text} for every top-level test file."""
    return {name: read_text(os.path.join(workspace, name)) for name in test_files(workspace)}


def test_ids(tests):
    """{'test_x.Class.test_y': source} across a snapshot."""
    ids = {}
    for name, text in tests.items():
        for method, source in _methods(text).items():
            ids["%s.%s" % (name[:-3], method)] = source
    return ids


def run_one_test(workspace, test_id, seconds=120):
    """('passed' | 'failed' | 'error', output) for one unittest id."""
    try:
        proc = subprocess.run([find_project_python(workspace), "-m", "unittest", "-q", test_id],
                              cwd=workspace, capture_output=True, text=True, timeout=seconds,
                              encoding="utf-8", errors="replace", env=_import_env())
    except subprocess.TimeoutExpired:
        return "error", "timed out after %ds" % seconds
    except OSError as exc:
        return "error", str(exc)
    out = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode == 0:
        return "passed", out
    return ("failed" if "FAIL:" in out and "ERROR:" not in out else "error"), out


def put_files(workspace, files):
    """Write {name: text}; a text of None deletes the file."""
    for name, text in files.items():
        path = os.path.join(workspace, name)
        if text is None:
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            write_text(path, text)


def untick(notes_path, task_text):
    """Open the item again if a round ticked it. True if it did."""
    body = read_text(notes_path)
    pattern = re.compile(r"^([ \t]*[-*][ \t]*)\[[xX]\]([ \t]*%s[ \t]*)$" % re.escape(task_text),
                         re.MULTILINE)
    fixed, count = pattern.subn(r"\1[ ]\2", body, count=1)
    return bool(count) and write_text(notes_path, fixed)


def last_words(out):
    lines = [l for l in (out or "").splitlines() if l.strip() and not set(l.strip()) <= set("-=")]
    return lines[-1].strip()[:140] if lines else "(no output)"


TEST_ROUND = """# THIS ROUND: THE TEST ONLY

The item at the top of the list will be done in the next round. This round
writes the test that proves it, and nothing else.

Item: {item}

Write one unittest in `{test_file}` (create it if it does not exist) that
checks exactly this:

    {check}

- Import what it tests from the project; do not copy code into the test.
- It must FAIL on the code as it stands now -- that is how we know it tests
  something. If what it tests does not exist yet, failing to import it is fine.
- Change no other file. Tick nothing. The loop runs the test after this round.
"""

CODE_ROUND = """# THIS ITEM HAS A TEST

{tests} was written for this item in an earlier round and fails now. The item
is done when it passes and every other test still does. Change the code, not
the test: the test is put back as it was after every round.
"""

SETTLED_BY_TEST = ("\nSettled by execution: the item's own test ({tests}) was written in an "
                   "earlier round and failed before this change; after it, that test and "
                   "every other test pass. Judge scope and collateral damage, not whether "
                   "it works.\n")


class TestFirstMixin:
    """Part of Session: the test round, and the code rounds after it.

    pending_tests[item] = {"ids": [...], "files": {name: (before, after)},
    "kept": bool} -- the test written for an item, the test files as they
    were before and after the test round, and whether it is in the history.
    """

    def round_phase(self, task):
        """'test' for an item a test could check that has none yet, else 'code'."""
        if not TEST_FIRST or self.single_shot or self.broken or task in self.pending_tests:
            return "code"
        if self.test_misses.get(task, 0) >= TEST_TRIES:
            return "code"
        return "test" if acceptance(task) and self.test_target(task) else "code"

    def test_target(self, task):
        from ralph_rounds import files_for_task
        return test_file_for(task, files_for_task(task, self.edit_files) or self.edit_files)

    def phase_note(self, task, phase):
        """The header this round's prompt starts with, for its phase."""
        if phase == "test":
            return TEST_ROUND.format(item=task, test_file=self.test_target(task),
                                     check=acceptance(task))
        pending = self.pending_tests.get(task)
        if pending and not pending["kept"]:
            return CODE_ROUND.format(tests=", ".join("`%s`" % t for t in pending["ids"]))
        return ""

    def put_test_back(self, task):
        """Before a code round: the item's unkept test goes back in the tree."""
        pending = self.pending_tests.get(task)
        if not pending or pending["kept"]:
            self.review_note = ""
            return
        put_files(self.workspace, {n: after for n, (_, after) in pending["files"].items()})
        self.review_note = SETTLED_BY_TEST.format(
            tests=", ".join("`%s`" % t for t in pending["ids"]))

    def hold_test(self, task):
        """After a code round, before its checks: undo any change to the test."""
        pending = self.pending_tests.get(task)
        if not pending or pending["kept"]:
            return
        now = snapshot(self.workspace)
        if any(now.get(n) != after for n, (_, after) in pending["files"].items()):
            self.note("  the round changed the item's test; put back as written.")
            put_files(self.workspace, {n: after for n, (_, after) in pending["files"].items()})

    def settle_test(self, task, kept):
        """After a code round's checks: kept with the change, or out of the tree."""
        pending = self.pending_tests.get(task)
        if not pending or pending["kept"]:
            return
        if kept:
            pending["kept"] = True
            self.note("  the item's test passes, and is kept with the change.")
            return
        # Not kept: rolled back, rejected, or nothing changed. The test is
        # taken out again, so no later item inherits a failing test.
        put_files(self.workspace, {n: before for n, (before, _) in pending["files"].items()})
        failing = [msg for where, msg in self.broken if where == "tests"]
        if failing:
            from ralph_tasks import remember_review
            remember_review(self.notes_path, task, "its test still fails -- %s"
                            % " ".join(failing[0].split())[:160])
        if self.broken:
            from ralph_checks import full_check
            self.broken = full_check(self.workspace, self.edit_files, self.entry,
                                     self.run_seconds)

    def after_test_round(self, result, task, tests_before, code_before, listing_before):
        """Judge a test round. False to stop."""
        ws = self.workspace
        self.refresh_files()
        tests_after = snapshot(ws)
        ids_before, ids_after = test_ids(tests_before), test_ids(tests_after)
        new = sorted(t for t in ids_after if t not in ids_before)
        changed_code = code_fingerprint(self.non_test_files()) != code_before
        changed = {n: (tests_before.get(n), tests_after.get(n))
                   for n in set(tests_before) | set(tests_after)
                   if tests_before.get(n) != tests_after.get(n)}
        if untick(self.notes_path, task):
            self.note("  ticked it in the test round; opened again.")

        # The tests already there are what every other change is held to. A
        # test round that edits one would carry the edit in with its own test.
        altered = sorted(t for t, source in ids_before.items() if ids_after.get(t) != source)
        why = ""
        if changed_code:
            why = "the test round changed code, not only a test"
        elif altered:
            why = "the test round changed an existing test (%s)" % altered[0]
        elif not new:
            broken = [n for n, (_, after) in changed.items() if after and not _methods(after)]
            why = ("%s does not parse" % broken[0]) if broken else \
                "no new test method was written"
        else:
            outcomes = {t: run_one_test(ws, t) for t in new[:5]}
            ran = [(t, o, out) for t, (o, out) in outcomes.items()]
            unusable = [(t, out) for t, o, out in ran if o == "error"
                        and not MISSING_YET.search(out)]
            if unusable:
                why = "the new test does not run (%s): %s" % (unusable[0][0], last_words(unusable[0][1]))
            elif all(o == "passed" for _, o, _ in ran):
                why = "the new test passes before any change, so it does not test the item"

        # Out of the tree either way: kept aside on success, dropped on failure.
        put_files(ws, {n: before for n, (before, _) in changed.items()})
        if changed_code and self.rollback and self.rollback():
            self.remove_new_sources(listing_before)

        if why:
            self.test_misses[task] = self.test_misses.get(task, 0) + 1
            self.stalled += 1
            self.note("Test round sent back: %s" % why[:110])
            from ralph_tasks import remember_review
            from ralph_tools import record_lesson
            remember_review(self.notes_path, task, "test round: " + why)
            record_lesson(ws, "Test round failed: %s -- %s" % (task[:80], why[:100]),
                          kind="test-first")
            self.last_failure_kind = "test-first"
        else:
            self.pending_tests[task] = {"ids": new, "files": changed, "kept": False}
            self.stalled = 0
            self.note("Test written: %s. Next, the code that makes it pass."
                      % ", ".join(new)[:110])
        self.ledger_round(result, bool(changed), "reject" if why else "accept",
                          "test round: " + (why or "fails as it should"), [], 0, False, "")
        return self.finish_round(result, True)
