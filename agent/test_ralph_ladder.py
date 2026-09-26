"""The escalation ladder: each try at a failing item is made differently."""

import contextlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from collections import namedtuple

import ralph_ledger
import status
from ralph_common import read_text, write_text
from ralph_ladder import next_rung, outcome, rung_command
from ralph_session import Session

R = namedtuple("R", "failed applied")


class TestRungs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.small = os.path.join(self.dir, "small.py")
        write_text(self.small, "x = 1\n")
        self.big = os.path.join(self.dir, "big.py")
        write_text(self.big, "x = 1\n" * 400)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_what_went_wrong_picks_the_next_try(self):
        self.assertEqual(next_rung([], [self.small]), "plain")
        self.assertEqual(next_rung(["kept"], [self.small]), "plain")
        self.assertEqual(next_rung(["broke"], [self.small]), "architect")
        self.assertEqual(next_rung(["no-change"], [self.small]), "architect")
        self.assertEqual(next_rung(["edit-missed"], [self.small]), "whole")
        self.assertEqual(next_rung(["edit-missed"], [self.big]), "plain")
        self.assertEqual(next_rung(["rejected"], [self.small]), "plain")

    def test_two_failures_ask_for_a_split_once(self):
        self.assertEqual(next_rung(["broke", "rejected"], [self.small]), "split")
        self.assertEqual(next_rung(["broke", "rejected", "split", "no-change"], [self.small]),
                         "architect")
        self.assertEqual(next_rung(["broke", "kept", "rejected"], [self.small]), "plain")

    def test_outcomes(self):
        self.assertEqual(outcome(R(0, 1), True, True, False, False), "kept")
        self.assertEqual(outcome(R(0, 1), True, False, False, True), "broke")
        self.assertEqual(outcome(R(0, 1), False, False, True, False), "rejected")
        self.assertEqual(outcome(R(2, 0), False, False, False, False), "edit-missed")
        self.assertEqual(outcome(R(0, 0), False, False, False, False), "no-change")

    def test_the_command_for_each_rung(self):
        base = ["aider", "--edit-format", "diff"]
        self.assertEqual(rung_command(base, "whole"), ["aider", "--edit-format", "whole"])
        self.assertEqual(rung_command(base, "architect"), base + ["--architect"])
        self.assertEqual(rung_command(base, "split"), base)
        self.assertEqual(base, ["aider", "--edit-format", "diff"])        # not changed


# Records each round's command and message; changes nothing, so every try fails.
IDLE = r'''import json, os, sys
args = sys.argv[1:]
message = open(args[args.index("--message-file") + 1], encoding="utf-8").read()
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.jsonl"), "a") as h:
    h.write(json.dumps({"args": args, "split": "SPLIT THE ITEM" in message}) + "\n")
if os.environ.get("FAKE_MISS"):
    print("# 1 SEARCH/REPLACE block failed to match!")
print("Tokens: 1k sent, 100 received.")
'''


class TestTheLadderInALoop(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.join(self.dir, "ws")
        os.makedirs(self.ws)
        self.fake = os.path.join(self.dir, "fake.py")
        write_text(self.fake, IDLE)
        write_text(os.path.join(self.ws, "tasks.md"), "# Tasks\n\n- [ ] In `add` (calc.py), handle None\n")
        self.code = os.path.join(self.ws, "calc.py")
        write_text(self.code, "def add(a, b):\n    return a + b\n")
        status._path = None

    def tearDown(self):
        status._path = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def calls(self, **env):
        s = Session([sys.executable, self.fake, "--edit-format", "diff"], self.ws,
                    dict(os.environ, **env), minutes=3, single_shot=False,
                    edit_files=[self.code], entry_hint="none", iteration_timeout=30)
        with contextlib.redirect_stdout(io.StringIO()):
            s.run()
        import json
        return [json.loads(l) for l in read_text(os.path.join(self.dir, "calls.jsonl")).splitlines()]

    def test_changed_nothing_then_architect_then_a_split(self):
        calls = self.calls()
        self.assertNotIn("--architect", calls[0]["args"])
        self.assertIn("--architect", calls[1]["args"])
        self.assertTrue(calls[2]["split"])
        self.assertIn("asking for it to be split",
                      read_text(os.path.join(self.ws, ".localcoder-ralph.log")))

    def test_edits_that_miss_are_made_whole(self):
        calls = self.calls(FAKE_MISS="1")
        second = calls[1]["args"]
        self.assertEqual(second[second.index("--edit-format") + 1], "whole")


class TestLedgerGrows(unittest.TestCase):
    def test_an_old_ledger_gets_the_new_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ralph_ledger.LEDGER_FILE)
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE rounds (id INTEGER PRIMARY KEY, at REAL, item TEXT)")
            db.commit()
            db.close()
            self.assertTrue(ralph_ledger.record(tmp, item="x", rung="architect"))
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute("SELECT rung FROM rounds").fetchall(), [("architect",)])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
