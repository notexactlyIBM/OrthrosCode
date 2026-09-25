"""Tests for the task list, the plan and the progress ledger."""

import os
import shutil
import tempfile
import unittest

from ralph_common import ROUNDS_IF_BIG, ROUNDS_IF_SMALL, read_text, write_text
from ralph_tasks import (add_items, done_count, milestones, next_milestone,
                         normalize_checkboxes, normalize_plan, open_tasks, park_milestone,
                         park_task, progress_regressions, progress_rows, progress_summary,
                         record_progress, remember_review, triage)


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.notes = os.path.join(self.dir, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [ ] In `add`, handle None\n- [x] done one\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestLooseForms(Temp):
    def test_plan_headings_without_boxes_become_milestones(self):
        plan = os.path.join(self.dir, "PLAN.md")
        write_text(plan, "# Plan\n\n## [x] Old\n\nb\n\n## 1. Better research\n\nx\n\n"
                         "### Milestone 2: Faster checks\n")
        self.assertEqual(normalize_plan(plan), 2)
        self.assertEqual(next_milestone(plan), ("Better research", "x"))

    def test_plan_with_a_pending_milestone_is_left_alone(self):
        plan = os.path.join(self.dir, "PLAN.md")
        write_text(plan, "# Plan\n\n## [ ] Real\n\n## Notes\n")
        self.assertEqual(normalize_plan(plan), 0)

    def test_numbered_and_empty_boxes_become_items(self):
        write_text(self.notes, "# T\n\n1. [ ] one\n- [] two\n  + [ ] three\n- [ ] four\n")
        self.assertEqual(normalize_checkboxes(self.notes), 3)
        self.assertEqual(open_tasks(self.notes), ["one", "two", "three", "four"])

    def test_parked_milestone_is_skipped(self):
        plan = os.path.join(self.dir, "PLAN.md")
        write_text(plan, "# Plan\n\n## [ ] Stuck\n\na\n\n## [ ] Next\n\nb\n")
        self.assertTrue(park_milestone(plan, "Stuck", "no items came of it"))
        self.assertEqual(next_milestone(plan), ("Next", "b"))
        self.assertEqual([m[0] for m in milestones(plan)], ["Next"])


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

    def test_remember_review_keeps_last_two_reasons(self):
        remember_review(self.notes, "In `add`, handle None", "first reason")
        remember_review(self.notes, "In `add`, handle None", "second reason")
        body = read_text(self.notes)
        self.assertIn("first reason", body)
        self.assertIn("second reason", body)
        self.assertEqual(body.count("*Review*"), 2)

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


class TestRememberReview(unittest.TestCase):
    def test_keeps_last_two_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = os.path.join(tmp, "tasks.md")
            with open(notes, "w", encoding="utf-8") as f:
                f.write("# Tasks\n\n- [ ] Do the thing\n")
            task = "Do the thing"
            remember_review(notes, task, "first reason")
            remember_review(notes, task, "second reason")
            remember_review(notes, task, "third reason")
            with open(notes, encoding="utf-8") as f:
                body = f.read()
            self.assertIn("second reason", body)
            self.assertIn("third reason", body)
            self.assertNotIn("first reason", body)
            reviews = [line for line in body.splitlines() if "*Review*:" in line]
            self.assertEqual(len(reviews), 2)


if __name__ == "__main__":
    unittest.main()
