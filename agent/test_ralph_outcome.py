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


if __name__ == "__main__":
    unittest.main()
