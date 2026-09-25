"""Tests for OutcomeMixin._record_failure."""

import os
import tempfile
import unittest

from ralph_outcome import OutcomeMixin


class _FakeResult:
    def __init__(self, symptom="", crowded=False):
        self.symptom = symptom
        self.crowded = crowded


class _FakeSession:
    def __init__(self, workspace):
        self.workspace = workspace
        self.current_task = "test task"


class TestRecordFailure(unittest.TestCase):
    def test_truncated_reply_records_reply_cut_off(self):
        with tempfile.TemporaryDirectory() as workspace:
            session = _FakeSession(workspace)
            result = _FakeResult(symptom="context", crowded=False)

            OutcomeMixin._record_failure(session, result)

            lessons_path = os.path.join(workspace, "LESSONS.md")
            self.assertTrue(os.path.exists(lessons_path))
            with open(lessons_path, encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn("reply-cut-off", body)

    def test_inspection_only_records_lesson(self):
        with tempfile.TemporaryDirectory() as workspace:
            session = _FakeSession(workspace)
            result = _FakeResult(symptom="", crowded=False)

            OutcomeMixin._record_failure(session, result, ticked=1, touched=False)

            lessons_path = os.path.join(workspace, "LESSONS.md")
            self.assertTrue(os.path.exists(lessons_path))
            with open(lessons_path, encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn("inspection-only", body)
            self.assertEqual(session.last_failure_kind, "inspection-only")


class TestTheKindReachesThePrompt(unittest.TestCase):
    def test_the_next_round_puts_lessons_of_that_kind_first(self):
        from ralph_prompts import compose_round_prompt
        with tempfile.TemporaryDirectory() as workspace:
            with open(os.path.join(workspace, "LESSONS.md"), "w", encoding="utf-8") as h:
                h.write("# Lessons\n\n"
                        "- 2026-09-25 inspection-only: Ticked without code change: x\n"
                        + "".join("- 2026-09-25 Parked: In `add_it` (calc.py), try %d\n" % i
                                  for i in range(6)))
            prompt = os.path.join(workspace, "PROMPT.md")
            with open(prompt, "w", encoding="utf-8") as h:
                h.write("Work the list.\n")
            task = "In `add_it` (calc.py), handle None"
            def sent(**kind):
                with open(compose_round_prompt(workspace, prompt, [], task=task, **kind),
                          encoding="utf-8") as h:
                    return h.read()
            self.assertNotIn("inspection-only", sent())      # outranked by five name matches
            self.assertIn("inspection-only", sent(last_failure_kind="inspection-only"))


if __name__ == "__main__":
    unittest.main()
