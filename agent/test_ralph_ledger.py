"""The round ledger: one row per round, and where rounds go."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import ralph_ledger as ledger


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, ledger.LEDGER_FILE)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def rows(self):
        db = sqlite3.connect(self.path)
        try:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM rounds ORDER BY id")]
        finally:
            db.close()

    def test_a_round_is_one_row_with_the_diff_hashed(self):
        self.assertTrue(ledger.record(self.dir, item="In `add`, x", kept=1, diff="+x\n",
                                      not_a_column="dropped"))
        row, = self.rows()
        self.assertEqual(row["item"], "In `add`, x")
        self.assertEqual(len(row["diff_sha"]), 40)
        self.assertGreater(row["at"], 0)

    def test_orthros_points_both_agents_at_one_file(self):
        shared = os.path.join(self.dir, "shared.sqlite")
        with mock.patch.dict(os.environ, {"ORTHROS_LEDGER": shared}):
            ledger.record(self.dir, agent="A")
            ledger.record(self.dir, agent="B")
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(len(ledger.outcomes(shared, 0)), 1)

    def test_a_ledger_that_cannot_be_written_does_not_raise(self):
        self.assertFalse(ledger.record(os.path.join(self.dir, "no", "such", "folder"), kept=1))

    def test_outcomes_says_where_rounds_went(self):
        for row in ({"kept": 1, "verdict": "accept"}, {"kept": 1, "verdict": "accept"},
                    {"verdict": "reject"}, {"symptom": "context"},
                    {"failed": 2, "applied": 0}, {"caught": "placeholder"}):
            full = dict(symptom="", failed=0, applied=0, broken="", caught="", verdict="",
                        kept=0)
            full.update(row)
            ledger.record(self.dir, **full)
        self.assertEqual(ledger.outcomes(self.path, 0),
                         [("kept", 2), ("caught by a check", 1), ("edit did not apply", 1),
                          ("lost: context", 1), ("rejected by reviewer", 1)])
        self.assertEqual(ledger.outcomes(self.path, 2 ** 40), [])
        self.assertEqual(ledger.outcomes(os.path.join(self.dir, "none.sqlite"), 0), [])


if __name__ == "__main__":
    unittest.main()
