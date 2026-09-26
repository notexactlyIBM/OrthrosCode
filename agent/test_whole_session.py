"""A whole session through every part at once, against a scripted aider.

Each part has its own tests; this is the one that says they work together:
test rounds and code rounds, a code round that is wrong first, a reviewer
citing a fault that is not there, the ladder, the ledger and the examples.
Strict: a bug in the loop fails it instead of being survived.
"""

import contextlib
import io
import json
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

os.environ.setdefault("LC_RALPH_RAISE", "1")

ITEMS = """# Tasks

- [ ] In `double` (calc.py), return twice the number. Done when: `double(2)` returns 4.
- [ ] In `triple` (calc.py), return three times the number. Done when: `triple(2)` returns 6.
- [ ] In `halve` (calc.py), return half the number. Done when: `halve(8)` returns 4.
"""

# Test rounds write a test for the function the item names. Code rounds write
# it -- wrongly the first time for `triple`, right after.
FAKE = r'''import json, os, re, sys
args = sys.argv[1:]
message = open(args[args.index("--message-file") + 1], encoding="utf-8").read()
notes = [args[i + 1] for i, a in enumerate(args) if a == "--file"][0]
here = os.path.dirname(notes)
body = open(notes, encoding="utf-8").read()
item = re.search(r"^- \[ \] In `(\w+)`", body, re.M)
log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rounds.jsonl")
name = item.group(1) if item else ""
factor = {"double": 2, "triple": 3, "halve": 0.5}.get(name)
calc = os.path.join(here, "calc.py")
kind = ("test" if "THIS ROUND: THE TEST ONLY" in message else
        "refill" if not item else "code")
tries = sum(1 for l in open(log) if json.loads(l)["name"] == name and json.loads(l)["kind"] == "code") \
    if os.path.exists(log) else 0
open(log, "a").write(json.dumps({"kind": kind, "name": name,
                                 "examples": "How similar items were done here" in message,
                                 "architect": "--architect" in args}) + "\n")
if kind == "test":
    path = os.path.join(here, "test_calc.py")
    head = "" if os.path.exists(path) else "import unittest\nimport calc\n\n\nclass TestCalc(unittest.TestCase):\n"
    arg = 8 if name == "halve" else 2
    open(path, "a").write(head + "    def test_%s(self):\n        self.assertEqual(calc.%s(%d), %s)\n"
                          % (name, name, arg, int(arg * factor)))
elif kind == "code":
    wrong = name == "triple" and tries == 0
    code = "\n\ndef %s(x):\n    return %s\n" % (name, "x" if wrong else "x * %s" % factor
                                             if factor >= 1 else "x // 2")
    source = open(calc).read()
    old = re.search(r"\n\ndef %s\(x\):\n    return .*\n" % name, source)
    # As a model does: the function again, not a second copy of it.
    open(calc, "w").write(source.replace(old.group(0), code) if old else source + code)
    open(notes, "w").write(body.replace("- [ ] In `%s`" % name, "- [x] In `%s`" % name, 1))
print("Applied edit to calc.py")
print("Tokens: 1k sent, 100 received.")
'''

HAS_PYFLAKES = importlib.util.find_spec("pyflakes") is not None


def git(ws, *args):
    return subprocess.run(["git", "-C", ws, "-c", "user.name=t", "-c", "user.email=t@t"]
                          + list(args), capture_output=True, text=True)


class TestWholeSession(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.join(self.dir, "ws")
        os.makedirs(self.ws)
        self.fake = os.path.join(self.dir, "fake.py")
        write_text(self.fake, FAKE)
        self.notes = os.path.join(self.ws, "tasks.md")
        write_text(self.notes, ITEMS)
        write_text(os.path.join(self.ws, "calc.py"), '"""Arithmetic."""\n')
        git(self.ws, "init", "-q")
        git(self.ws, "add", "-A")
        git(self.ws, "commit", "-qm", "base")
        status._path = None
        self.patches = [mock.patch(m + ".find_project_python", return_value=sys.executable)
                        for m in ("ralph_checks", "ralph_testfirst")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        status._path = None
        shutil.rmtree(self.dir, ignore_errors=True)

    @unittest.skipUnless(HAS_PYFLAKES, "the lint checks need pyflakes (it comes with flake8)")
    def test_three_items_through_every_part(self):
        reviewed = []

        def review(task, diff, context="", notes=(), faults=None):
            reviewed.append((task, context))
            if len(reviewed) == 1:
                # The first change is sound; the reviewer claims a name is
                # undefined that the file defines. The claim must be dropped.
                faults.append({"kind": "undefined-name", "line": "def double(x):",
                               "why": "`double` is not defined"})
                return "reject", "double is undefined"
            return "accept", "fine"

        files = lambda: sorted(os.path.join(self.ws, n) for n in os.listdir(self.ws)  # noqa
                               if n.endswith(".py"))
        s = Session([sys.executable, self.fake, "--edit-format", "diff"], self.ws,
                    os.environ.copy(), minutes=4, single_shot=False, edit_files=files(),
                    entry_hint="none", iteration_timeout=30, review=review, list_files=files,
                    rollback=lambda: git(self.ws, "checkout", "--", ".").returncode == 0,
                    commit=lambda m: (git(self.ws, "add", "-A"), git(self.ws, "commit", "-qm", m))
                    and True)
        with contextlib.redirect_stdout(io.StringIO()):
            s.run()
        log = read_text(os.path.join(self.ws, ".localcoder-ralph.log"))
        rounds = [json.loads(l) for l in read_text(os.path.join(self.dir, "rounds.jsonl"))
                  .splitlines()]
        notes = read_text(self.notes)

        self.assertNotIn("unexpected error", log)
        # Every item done, each by a test round and then code that passes it.
        for name in ("double", "triple", "halve"):
            self.assertIn("- [x] In `%s`" % name, notes)
            kinds = [r["kind"] for r in rounds if r["name"] == name]
            self.assertEqual(kinds[0], "test", name)
            self.assertIn("code", kinds, name)
        # The false claim was dropped, and the change kept.
        self.assertIn("reviewer's claim dropped", log)
        # triple's first code was wrong: the test caught it, and the ladder
        # tried the next one differently.
        triple = [r for r in rounds if r["name"] == "triple" and r["kind"] == "code"]
        self.assertGreaterEqual(len(triple), 2)
        self.assertTrue(triple[1]["architect"])
        told = [c for t, c in reviewed if "`triple`" in t]
        self.assertIn("Not settled: the item's own test", told[0])
        self.assertIn("Settled by execution", told[-1])
        # The history holds each test with the code that passes it.
        committed_tests = git(self.ws, "show", "HEAD:test_calc.py").stdout
        for name in ("double", "triple", "halve"):
            self.assertIn("def test_%s" % name, committed_tests)
        self.assertEqual(subprocess.run([sys.executable, "-m", "unittest", "-q", "test_calc"],
                                        cwd=self.ws, capture_output=True).returncode, 0)
        # Every kept round is remembered for later examples (retrieval itself,
        # which needs more history than three items to clear its bar, is
        # tested in test_ralph_memory).
        self.assertGreaterEqual(len(s.memory.items), 3)
        # And the ledger has every round.
        went = dict(ralph_ledger.outcomes(os.path.join(self.ws, ralph_ledger.LEDGER_FILE), 0))
        self.assertGreaterEqual(went.get("kept", 0), 3)


if __name__ == "__main__":
    unittest.main()
