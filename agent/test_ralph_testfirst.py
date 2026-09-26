"""Test first, then code (ralph_testfirst.py), end to end against a fake aider."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import importlib.util
import unittest
from unittest import mock

import ralph_ledger
import status
from ralph_common import read_text, write_text
from ralph_session import Session
from ralph_testfirst import acceptance, test_file_for, test_is_broken, untick

# A bug in the loop fails the test instead of being logged and survived: that
# is how a crash in the refill hid behind a passing suite on 2026-09-26.
os.environ.setdefault("LC_RALPH_RAISE", "1")

ITEM = "In `double` (calc.py), return twice the number. Done when: `double(2)` returns 4."

# Plays both kinds of round. FAKE_TEST says what the test round writes;
# FAKE_CODE what the code round does.
FAKE = r'''import os, re, sys
args = sys.argv[1:]
message = open(args[args.index("--message-file") + 1], encoding="utf-8").read()
notes = [args[i + 1] for i, a in enumerate(args) if a == "--file"][0]
here = os.path.dirname(notes)
test_kind, code_kind = os.environ["FAKE_TEST"], os.environ["FAKE_CODE"]
if "THIS ROUND: THE TEST ONLY" in message:
    check = "calc.double(2), 4" if test_kind != "passes" else "calc.add(2, 2), 4"
    open(os.path.join(here, "test_calc.py"), "w").write(
        "import unittest\nimport calc\n\n\nclass TestDouble(unittest.TestCase):\n"
        "    def test_double(self):\n"
        "        self.assertEqual(%s)\n" % check)
    if test_kind == "and_old":
        path = os.path.join(here, "test_old.py")
        open(path, "w").write(open(path).read().replace("(1, 1)", "(1, 1 + 0)"))
    if test_kind == "and_code":
        open(os.path.join(here, "calc.py"), "a").write("\n\ndef double(x):\n    return 2 * x\n")
    # A habit worth guarding against: ticking the item anyway.
    body = open(notes).read()
    open(notes, "w").write(body.replace("- [ ] In `double`", "- [x] In `double`"))
else:
    body = open(notes).read()
    if code_kind in ("right", "cheat"):
        open(os.path.join(here, "calc.py"), "a").write("\n\ndef double(x):\n    return 2 * x\n")
        open(notes, "w").write(body.replace("- [ ] In `double`", "- [x] In `double`"))
    if code_kind == "cheat":
        path = os.path.join(here, "test_calc.py")
        open(path, "w").write(open(path).read().replace("calc.double(2), 4", "4, 4"))
        open(os.path.join(here, "calc.py"), "a").write("\n\ndef double(x):\n    return 0\n")
    if code_kind == "nothing_useful":
        open(os.path.join(here, "calc.py"), "a").write("\n\ndef double(x):\n    return x\n")
print("Tokens: 1k sent, 100 received.")
'''

HAS_PYFLAKES = importlib.util.find_spec("pyflakes") is not None


class TestAcceptance(unittest.TestCase):
    def test_a_code_item_with_a_checkable_done_when(self):
        self.assertEqual(acceptance(ITEM), "`double(2)` returns 4.")

    def test_items_with_nothing_to_run(self):
        self.assertEqual(acceptance("In `double` (calc.py), return twice the number."), "")
        self.assertEqual(acceptance("In SKILLS.md, explain FIND:. Done when: it is there."), "")
        self.assertEqual(acceptance("Tidy things up. Done when: it is tidy."), "")

    def test_where_the_test_goes(self):
        self.assertEqual(test_file_for(ITEM, ["/w/calc.py"]), "test_calc.py")
        self.assertEqual(test_file_for("Done when: a test in test_report.py passes",
                                       ["/w/calc.py"]), "test_report.py")
        self.assertEqual(test_file_for(ITEM, []), "")

    def test_honest_errors_of_unwritten_code_are_fine(self):
        item = "In `add` (calc.py), take a third argument. Done when: add(1, 2, 3) returns 6."
        for out in ("TypeError: add() takes 2 positional arguments but 3 were given",
                    "ImportError: cannot import name 'double' from 'calc'",
                    "AttributeError: module 'calc' has no attribute 'double'",
                    "KeyError: 'total'"):
            self.assertEqual(test_is_broken(out, item), "", out)

    def test_a_test_that_can_never_pass_is_broken(self):
        item = "In `add` (calc.py), take a third argument. Done when: add(1, 2, 3) returns 6."
        self.assertIn("calcc", test_is_broken(
            "ModuleNotFoundError: No module named 'calcc'", item))
        self.assertEqual(test_is_broken("ModuleNotFoundError: No module named 'money'",
                                        "Add money.py with `Money`. Done when: x"), "")
        self.assertIn("never defines", test_is_broken(
            'File "/w/test_calc.py", line 8, in test_x\n    self.assertEqual(ad(1), 2)\n'
            "NameError: name 'ad' is not defined", item))
        self.assertIn("parse", test_is_broken("SyntaxError: invalid syntax", item))

    def test_untick(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = os.path.join(tmp, "tasks.md")
            write_text(notes, "- [x] %s\n- [x] other\n" % ITEM)
            self.assertTrue(untick(notes, ITEM))
            self.assertEqual(read_text(notes), "- [ ] %s\n- [x] other\n" % ITEM)
            self.assertFalse(untick(notes, "missing"))


class TestTestFirstLoop(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.join(self.dir, "ws")
        os.makedirs(self.ws)
        self.fake = os.path.join(self.dir, "fake_aider.py")
        write_text(self.fake, FAKE)
        self.notes = os.path.join(self.ws, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [ ] %s\n" % ITEM)
        self.code = os.path.join(self.ws, "calc.py")
        write_text(self.code, "def add(a, b):\n    return a + b\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        status._path = None
        # The checks run tests with the project's own Windows venv, which is
        # not here; this interpreter stands in for it.
        self.python = [mock.patch(where + ".find_project_python", return_value=sys.executable)
                       for where in ("ralph_checks", "ralph_testfirst")]
        for patch in self.python:
            patch.start()

    def tearDown(self):
        for patch in self.python:
            patch.stop()
        status._path = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.ws, "-c", "user.name=t", "-c", "user.email=t@t"]
                              + list(args), capture_output=True, text=True)

    def run_session(self, test_kind, code_kind, review=None):
        env = dict(os.environ, FAKE_TEST=test_kind, FAKE_CODE=code_kind)
        files = lambda: sorted(os.path.join(self.ws, n) for n in os.listdir(self.ws)  # noqa: E731
                               if n.endswith(".py"))
        s = Session([sys.executable, self.fake, "--edit-format", "diff"], self.ws, env,
                    minutes=3, single_shot=False, edit_files=files(), entry_hint="none",
                    iteration_timeout=30, review=review or (lambda task, diff: ("accept", "ok")),
                    list_files=files,
                    rollback=lambda: self.git("checkout", "--", ".").returncode == 0,
                    commit=lambda m: (self.git("add", "-A"), self.git("commit", "-qm", m)) and True)
        with contextlib.redirect_stdout(io.StringIO()):
            s.run()
        self.log = read_text(os.path.join(self.ws, ".localcoder-ralph.log"))
        return s

    def committed(self, name):
        return self.git("show", "HEAD:%s" % name).stdout

    def test_the_test_then_the_code_and_both_are_kept(self):
        s = self.run_session("fails", "right")
        self.assertIn("Test written: test_calc.TestDouble.test_double", self.log)
        self.assertIn("- [x] In `double`", read_text(self.notes))
        self.assertIn("calc.double(2), 4", self.committed("test_calc.py"))
        self.assertIn("def double", self.committed("calc.py"))
        # Never on its own: no commit holds the test without the code.
        for sha in self.git("log", "--format=%H").stdout.split():
            test = self.git("show", "%s:test_calc.py" % sha)
            if test.returncode == 0:
                self.assertIn("def double", self.git("show", "%s:calc.py" % sha).stdout)
        self.assertEqual(s.rejected, 0)
        went = dict(ralph_ledger.outcomes(os.path.join(self.ws, ralph_ledger.LEDGER_FILE), 0))
        self.assertGreaterEqual(went.get("kept", 0), 1)

    def test_a_test_that_already_passes_is_sent_back(self):
        self.run_session("passes", "right")
        self.assertIn("passes before any change", self.log)
        # After two, the item is coded without one, and no test file is left over.
        self.assertIn("- [x] In `double`", read_text(self.notes))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "test_calc.py")))

    def test_a_test_round_that_writes_code_is_undone(self):
        self.run_session("and_code", "nothing_useful")
        self.assertIn("changed code, not only a test", self.log)
        self.assertNotIn("return 2 * x", read_text(self.code))

    def test_a_test_round_that_edits_an_old_test_is_sent_back(self):
        old = os.path.join(self.ws, "test_old.py")
        write_text(old, "import unittest\n\n\nclass TestOld(unittest.TestCase):\n"
                        "    def test_one(self):\n        self.assertEqual(1, 1)\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "old test")
        self.run_session("and_old", "right")
        self.assertIn("changed an existing test (test_old.TestOld.test_one)", self.log)
        self.assertIn("(1, 1)", read_text(old))
        self.assertIn("(1, 1)", self.committed("test_old.py"))

    def test_code_that_never_passes_leaves_no_failing_test_behind(self):
        s = self.run_session("fails", "nothing_useful")
        self.assertIn("- [!] In `double`", read_text(self.notes))     # parked
        self.assertFalse(os.path.exists(os.path.join(self.ws, "test_calc.py")))
        self.assertEqual(self.committed("test_calc.py"), "")
        self.assertFalse(s.broken)

    @unittest.skipUnless(HAS_PYFLAKES, "the lint checks need pyflakes (it comes with flake8)")
    def test_a_round_that_changes_the_test_gets_it_back(self):
        self.run_session("fails", "cheat")
        self.assertIn("changed the item's test; put back", self.log)
        self.assertNotIn("return 0", self.committed("calc.py"))
        self.assertNotIn("4, 4", read_text(os.path.join(self.ws, "test_calc.py"))
                         if os.path.exists(os.path.join(self.ws, "test_calc.py")) else "")

    def test_a_test_whose_file_changed_since_is_written_again(self):
        s = self.run_session("fails", "nothing_useful")
        s.pending_tests[ITEM] = {"ids": ["test_calc.T.test_x"], "kept": False,
                                 "files": {"test_calc.py": (None, "old text")}}
        write_text(os.path.join(self.ws, "test_calc.py"), "other item's tests\n")
        s.current_task = ITEM
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.round_phase(ITEM), "test")
        self.assertNotIn(ITEM, s.pending_tests)

    def test_code_that_gets_closer_is_kept_while_its_test_waits(self):
        self.run_session("fails", "nothing_useful")
        self.assertIn("the item's test still fails; the change is kept, the test waits", self.log)
        self.assertNotIn("unexpected error", self.log)
        self.assertNotIn("Broke start-up", self.log)
        self.assertIn("def double(x):\n    return x", self.committed("calc.py"))
        self.assertEqual(self.committed("test_calc.py"), "")

    def test_the_reviewer_is_told_what_the_test_settled(self):
        told = []

        def review(task, diff, context="", notes=()):
            told.append(context)
            return "accept", "ok"
        self.run_session("fails", "right", review=review)
        self.assertTrue(any("Settled by execution" in c for c in told))


if __name__ == "__main__":
    unittest.main()
