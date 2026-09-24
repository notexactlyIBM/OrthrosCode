"""End-to-end: a whole session against a fake aider, no model, no GPU.

The one test that says the loop still works as a loop -- setup, rounds,
review, recovery from its own errors, the summary -- after a change to any
part of it. Runs in seconds.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

import subprocess

import status
from ralph_common import read_text, write_text
from ralph_refill import refill_temperature
from ralph_session import Session

FAKE_AIDER = '''import os, re, sys
args = sys.argv[1:]
files = [args[i + 1] for i, a in enumerate(args) if a == "--file"]
if os.environ.get("FAKE_MODE") == "dead":
    print("litellm.APIConnectionError: Connection refused")
    sys.exit(1)
notes = files[0]
body = open(notes, encoding="utf-8").read()
open(notes, "w", encoding="utf-8").write(re.sub(r"- \\[ \\]", "- [x]", body, count=1))
for f in files[1:]:
    with open(f, "a", encoding="utf-8") as h:
        h.write("# touched\\n")
    print("Applied edit to %s" % os.path.basename(f))
print("Tokens: 1.2k sent, 300 received.")
'''


class TestLoop(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.join(self.dir, "ws")
        os.makedirs(self.ws)
        self.fake = os.path.join(self.dir, "fake_aider.py")
        write_text(self.fake, FAKE_AIDER)
        self.notes = os.path.join(self.ws, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [ ] In `add`, handle None\n"
                               "- [ ] In `sub`, handle None\n")
        self.code = os.path.join(self.ws, "calc.py")
        write_text(self.code, "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n"
                              "    return a - b\n")
        status._path = None
        self.env = os.environ.copy()

    def tearDown(self):
        status._path = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def session(self, **options):
        return Session([sys.executable, self.fake, "--edit-format", "diff"], self.ws, self.env,
                       minutes=3, single_shot=False, edit_files=[self.code], entry_hint="none",
                       iteration_timeout=30, **options)

    def run_quietly(self, session):
        with contextlib.redirect_stdout(io.StringIO()):
            return session.run()

    def test_works_the_list_and_survives_a_bad_reviewer(self):
        calls = []

        def review(task, diff):
            calls.append(task)
            if len(calls) == 1:
                raise RuntimeError("reviewer blew up")
            return "accept", "fine"

        commits = []
        s = self.session(review=review, commit=lambda msg: commits.append(msg) or True)
        self.assertEqual(self.run_quietly(s), 0)
        self.assertNotIn("- [ ]", read_text(self.notes))
        self.assertEqual(s.accepted, 1)
        self.assertGreaterEqual(s.tokens_in, 2400)
        self.assertEqual(status.read(self.ws).get("phase"), "finished")
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "PROGRESS.md")))

    def test_dead_engine_stops_cleanly(self):
        self.env["FAKE_MODE"] = "dead"
        s = self.session()
        self.assertEqual(self.run_quietly(s), 0)
        self.assertIn("reload", s.stop_reason.lower())
        self.assertEqual(status.read(self.ws).get("phase"), "finished")


# Refills write a plan or add items; work rounds tick one and touch the code.
REFILLING_AIDER = r'''import os, re, sys
args = sys.argv[1:]
files = [args[i + 1] for i, a in enumerate(args) if a == "--file"]
notes = files[0]
body = open(notes, encoding="utf-8").read()
if notes.endswith("PLAN.md"):
    open(notes, "a", encoding="utf-8").write("\n## [ ] Handle None\n\nMake them safe.\n")
elif "- [ ]" not in body:
    open(notes, "a", encoding="utf-8").write(
        "\n- [ ] In `add`, handle None\n- [ ] In `sub`, handle None\n")
else:
    open(notes, "w", encoding="utf-8").write(re.sub(r"- \[ \]", "- [x]", body, count=1))
    for f in files[1:]:
        if f.endswith(".py"):
            open(f, "a", encoding="utf-8").write("# touched\n")
            print("Applied edit to %s" % os.path.basename(f))
print("Tokens: 1.2k sent, 300 received.")
'''


class TestLoopWithGit(unittest.TestCase):
    """The rollback is real here: `git checkout -- .`, as in a managed folder."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.join(self.dir, "ws")
        os.makedirs(self.ws)
        self.fake = os.path.join(self.dir, "fake_aider.py")
        write_text(self.fake, REFILLING_AIDER)
        self.notes = os.path.join(self.ws, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [x] done already\n")
        self.code = os.path.join(self.ws, "calc.py")
        write_text(self.code, "def add(a, b):\n    return a + b\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        status._path = None

    def tearDown(self):
        status._path = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.ws, "-c", "user.name=t", "-c", "user.email=t@t"]
                              + list(args), capture_output=True, text=True)

    def run_session(self, review):
        s = Session([sys.executable, self.fake, "--edit-format", "diff"], self.ws,
                    os.environ.copy(), minutes=3, single_shot=False, edit_files=[self.code],
                    entry_hint="none", iteration_timeout=30, review=review,
                    rollback=lambda: self.git("checkout", "--", ".").returncode == 0,
                    commit=lambda m: (self.git("add", "-A"), self.git("commit", "-qm", m)) and True)
        with contextlib.redirect_stdout(io.StringIO()):
            s.run()
        return s

    def test_a_rejected_round_does_not_undo_the_refill_before_it(self):
        s = self.run_session(lambda task, diff: ("reject", "not what was asked"))
        log = read_text(os.path.join(self.ws, ".localcoder-ralph.log"))
        # Before: every rejection emptied the list, and the session ended on
        # "the item could not be parked" because the item had been undone too.
        self.assertNotIn("could not be", s.stop_reason)
        notes = read_text(self.notes)
        self.assertIn("- [!] In `add`", notes)       # both refilled items survived to be
        self.assertIn("- [!] In `sub`", notes)       # tried and parked, not wiped by undo
        # The same two ideas again are not new work: dropped, then it stops.
        self.assertIn("repeat ones already parked", log)
        self.assertEqual(read_text(self.notes).count("- [!] In `add`"), 1)


class TestLocateInALoop(TestLoop):
    def test_an_item_naming_no_file_asks_which_files(self):
        import ralph_rounds
        other = os.path.join(self.ws, "other.py")
        write_text(other, "def unrelated():\n    pass\n")
        write_text(self.notes, "# Tasks\n\n- [ ] Make adding safe when given nothing\n")
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return "calc.py"
        old = ralph_rounds.FALLBACK_TOKENS
        ralph_rounds.FALLBACK_TOKENS = 1          # too big to send whole: must locate
        try:
            s = Session([sys.executable, self.fake, "--edit-format", "diff"], self.ws, self.env,
                        minutes=3, single_shot=True, edit_files=[self.code, other],
                        entry_hint="none", iteration_timeout=30, ask=ask)
            with contextlib.redirect_stdout(io.StringIO()):
                s.run()
        finally:
            ralph_rounds.FALLBACK_TOKENS = old
        self.assertIn("located: calc.py", read_text(os.path.join(self.ws, ".localcoder-ralph.log")))
        self.assertIn("# touched", read_text(self.code))
        self.assertNotIn("# touched", read_text(other))
        self.assertEqual(len(asked), 1)


class TestRefillTemperature(unittest.TestCase):
    def test_checking_is_cold_inventing_is_warm(self):
        self.assertEqual(refill_temperature("verify", 0.2, 0.8), 0.2)
        self.assertEqual(refill_temperature("plan", 0.2, 0.8), 0.8)
        self.assertEqual(refill_temperature("brief", 0.2, 0.8), 0.8)
        self.assertEqual(refill_temperature("decompose", 0.2, 0.8), 0.5)


if __name__ == "__main__":
    unittest.main()
