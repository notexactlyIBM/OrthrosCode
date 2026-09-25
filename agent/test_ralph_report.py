"""Tests for the ten-minute checkpoint: when a run carries on, and when it stops."""

import os
import shutil
import tempfile
import unittest

from ralph_common import CHECKPOINT_ROUNDS, write_text
from ralph_report import ReportMixin
from ralph_tasks import park_task


class Desk(ReportMixin):
    """What the checkpoint reads, without a model or a loop around it."""

    def __init__(self, folder):
        self.notes_path = os.path.join(folder, "tasks.md")
        write_text(self.notes_path, "# Tasks\n\n- [ ] In `f`, return 2\n- [ ] In `g`, return 3\n")
        self.edit_files = [os.path.join(folder, "mod.py")]
        write_text(self.edit_files[0], "def f():\n    return 1\n")
        self.started = 0
        self.rounds = self.rejected = self.reverted = self.engine_failures = 0
        self.pace, self.broken, self.stop_reason = [], [], ""
        self.mark_checkpoint()

    def note(self, line):
        pass

    def stop(self, line):
        self.stop_reason = line.strip()


class TestCheckpoint(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.desk = Desk(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_changes_sent_back_are_the_loop_working_not_a_stall(self):
        # 2026-09-24: every round's change turned down by the reviewer, and
        # the checkpoint ended a 67-minute turn after 32.
        self.desk.rounds = self.desk.rejected = CHECKPOINT_ROUNDS
        self.assertTrue(self.desk.checkpoint())
        self.assertEqual(self.desk.stop_reason, "")

    def test_rounds_undone_for_breaking_it_count_too(self):
        self.desk.rounds = self.desk.reverted = CHECKPOINT_ROUNDS
        self.assertTrue(self.desk.checkpoint())

    def test_an_item_parked_is_the_loop_moving_on(self):
        self.desk.rounds = CHECKPOINT_ROUNDS
        park_task(self.desk.notes_path, "In `f`, return 2", "three rounds with nothing to show")
        self.assertTrue(self.desk.checkpoint())

    def test_rounds_that_did_nothing_at_all_still_stop_it(self):
        self.desk.rounds = CHECKPOINT_ROUNDS
        self.assertFalse(self.desk.checkpoint())
        self.assertIn("Nothing moved", self.desk.stop_reason)

    def test_the_next_look_starts_from_the_new_mark(self):
        self.desk.rounds = self.desk.rejected = CHECKPOINT_ROUNDS
        self.assertTrue(self.desk.checkpoint())
        self.desk.rounds += CHECKPOINT_ROUNDS       # more rounds, nothing sent back this time
        self.assertFalse(self.desk.checkpoint())
        self.assertIn("Nothing moved", self.desk.stop_reason)


if __name__ == "__main__":
    unittest.main()
