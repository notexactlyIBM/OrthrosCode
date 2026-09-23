"""Tests for the task list, the plan and the progress ledger."""

import os
import shutil
import tempfile
import unittest

from ralph_common import ROUNDS_IF_BIG, ROUNDS_IF_SMALL, read_text, write_text
from ralph_tasks import (add_items, done_count, milestones, next_milestone, open_tasks,
                         park_task, progress_regressions, progress_rows, progress_summary,
                         record_progress, remember_review, triage)


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.notes = os.path.join(self.dir, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [ ] In `add`, handle None\n- [x] done one\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestTriage(unittest.TestCase):
    def test_one_job_is_small(self):
        self.assertEqual(triage("In `Parser.read`, strip whitespace")[0], ROUNDS_IF_SMALL)

    def test_two_jobs_are_big(self):
        self.assertEqual(triage("Add a cache and log every miss")[0], ROUNDS_IF_BIG)

    def test_long_item_is_big(self):
        text = "Make the thing " + "really " * 15 + "good"
        self.assertEqual(triage(text)[0], ROUNDS_IF_BIG)

    def test_comma_inside_code_does_not_count(self):
        self.assertEqual(triage("In `load(path, strict)`, check the path")[0], ROUNDS_IF_SMALL)


class TestTaskList(Temp):
    def test_open_and_done(self):
        self.assertEqual(open_tasks(self.notes), ["In `add`, handle None"])
        self.assertEqual(done_count(self.notes), 1)

    def test_add_items_skips_duplicates(self):
        self.assertEqual(add_items(self.notes, "Found", ["new thing"]), 1)
        self.assertEqual(add_items(self.notes, "Found", ["new thing"]), 0)
        self.assertIn("- [ ] new thing", read_text(self.notes))

    def test_park_task(self):
        self.assertTrue(park_task(self.notes, "In `add`, handle None", "stuck"))
        self.assertIn("[!]", read_text(self.notes))
        self.assertEqual(open_tasks(self.notes), [])

    def test_remember_review_keeps_one_reason(self):
        remember_review(self.notes, "In `add`, handle None", "first reason")
        remember_review(self.notes, "In `add`, handle None", "second reason")
        body = read_text(self.notes)
        self.assertIn("second reason", body)
        self.assertEqual(body.count("*Review*"), 1)

    def test_write_text_leaves_no_temp_file(self):
        self.assertTrue(write_text(self.notes, "x"))
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])


class TestPlanAndProgress(Temp):
    def test_milestones(self):
        plan = os.path.join(self.dir, "PLAN.md")
        write_text(plan, "# Plan\n\n## [x] First\nbody one\n\n## [ ] Second\nbody two\n")
        self.assertEqual([(t, d) for t, _, d in milestones(plan)],
                         [("First", True), ("Second", False)])
        self.assertEqual(next_milestone(plan), ("Second", "body two"))

    def test_progress_rows_and_summary(self):
        for rounds, ticked in ((10, 5), (10, 6), (10, 7)):
            record_progress(self.notes, [rounds, ticked, 3, 1000, "50,000", "runs", "4/1"])
        rows = progress_rows(self.notes)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1][2], "7")
        self.assertIn("18 items finished", progress_summary(self.notes))

    def test_regression_is_noticed(self):
        for ticked in (8, 8, 8, 2):
            record_progress(self.notes, [10, ticked, 3, 1000, "1", "runs", "-"])
        self.assertTrue(any("items finished per round" in r
                            for r in progress_regressions(self.notes)))


if __name__ == "__main__":
    unittest.main()
