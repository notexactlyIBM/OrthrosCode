"""How similar items were done here: BM25 over past kept rounds in git."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import status
from ralph_common import read_text, write_text, session_test
from ralph_memory import Index, Memory, examples_note, kept_rounds, tokens
from ralph_session import Session

# A bug in the loop fails the test instead of being logged and survived: that
# is how a crash in the refill hid behind a passing suite on 2026-09-26.
os.environ.setdefault("LC_RALPH_RAISE", "1")


def git(ws, *args):
    return subprocess.run(["git", "-C", ws, "-c", "user.name=t", "-c", "user.email=t@t"]
                          + list(args), capture_output=True, text=True)


class TestIndex(unittest.TestCase):
    def test_names_are_split(self):
        self.assertIn("lesson", tokens("record_lesson"))
        self.assertIn("mixin", tokens("OutcomeMixin"))

    def test_the_closest_item_first(self):
        index = Index([("a", "In `record_lesson` (ralph_tools.py), trim old lines"),
                       ("b", "In `render` (gui.py), draw the HUD"),
                       ("c", "In `fold_old_lessons`, keep the newest lessons")])
        self.assertEqual([k for _, k in index.search("In `record_lesson`, skip repeats")][0], "a")
        self.assertEqual(index.search("nothing alike"), [])


@session_test
class TestMemoryFromGit(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        git(self.ws, "init", "-q")
        write_text(os.path.join(self.ws, "calc.py"), "def add(a, b):\n    return a + b\n")
        git(self.ws, "add", "-A")
        git(self.ws, "commit", "-qm", "base")
        write_text(os.path.join(self.ws, "calc.py"),
                   "def add(a, b):\n    if a is None or b is None:\n        raise TypeError\n"
                   "    return a + b\n")
        git(self.ws, "add", "-A")
        git(self.ws, "commit", "-qm",
            "LocalCoder ralph: round 1\n\nItem: In `add` (calc.py), refuse None")
        git(self.ws, "commit", "-q", "--allow-empty", "-m", "LocalCoder ralph: notes before round 2")

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_kept_rounds_come_back_with_their_items(self):
        self.assertEqual([i for _, i in kept_rounds(self.ws)], ["In `add` (calc.py), refuse None"])

    def test_a_similar_item_gets_the_kept_diff(self):
        found = Memory(self.ws).similar("In `sub` (calc.py), refuse None like `add` does")
        self.assertEqual(found[0][0], "In `add` (calc.py), refuse None")
        self.assertIn("+    if a is None or b is None:", found[0][1])
        self.assertIn("# How similar items were done here", examples_note(found))

    def test_the_same_item_is_not_its_own_example(self):
        self.assertEqual(Memory(self.ws).similar("In `add` (calc.py), refuse None"), [])

    def test_no_history_no_examples(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(Memory(empty).similar("In `add`, refuse None"), [])


FAKE = r'''import sys
args = sys.argv[1:]
files = [args[i + 1] for i, a in enumerate(args) if a == "--file"]
body = open(files[0]).read()
open(files[0], "w").write(body.replace("- [ ]", "- [x]", 1))
for f in files[1:]:
    if f.endswith(".py"):
        open(f, "a").write("\n# touched\n")
msg = open(args[args.index("--message-file") + 1]).read()
open(files[0] + ".prompts", "a").write(msg + "\n=====\n")
print("Tokens: 1k sent, 100 received.")
'''


@session_test
class TestTheLoopRemembers(unittest.TestCase):
    def test_a_kept_round_is_an_example_for_the_next_similar_item(self):
        d = tempfile.mkdtemp()
        try:
            ws = os.path.join(d, "ws")
            os.makedirs(ws)
            fake = os.path.join(d, "fake.py")
            write_text(fake, FAKE)
            notes = os.path.join(ws, "tasks.md")
            write_text(notes, "# Tasks\n\n- [ ] In `add` (calc.py), refuse None arguments\n"
                              "- [ ] In `add` (calc.py), refuse None and empty strings\n")
            code = os.path.join(ws, "calc.py")
            write_text(code, "def add(a, b):\n    return a + b\n")
            git(ws, "init", "-q")
            git(ws, "add", "-A")
            git(ws, "commit", "-qm", "base")
            status._path = None
            s = Session([sys.executable, fake], ws, os.environ.copy(), minutes=3,
                        single_shot=False, edit_files=[code], entry_hint="none",
                        iteration_timeout=30, review=lambda t, diff: ("accept", "ok"),
                        rollback=lambda: git(ws, "checkout", "--", ".").returncode == 0,
                        commit=lambda m: (git(ws, "add", "-A"), git(ws, "commit", "-qm", m))
                        and True)
            with contextlib.redirect_stdout(io.StringIO()):
                s.run()
            prompts = read_text(notes + ".prompts").split("=====")
            self.assertNotIn("How similar items were done here", prompts[0])
            self.assertIn("Item: In `add` (calc.py), refuse None arguments", prompts[1])
        finally:
            status._path = None
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
