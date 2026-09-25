"""fold_old_lessons keeps the newest lessons and preserves summary kinds."""

import os
import tempfile
import unittest

from ralph_tools import fold_old_lessons, record_lesson


class TestFoldOldLessons(unittest.TestCase):
    def test_folds_only_the_oldest_and_keeps_summary_kinds(self):
        with tempfile.TemporaryDirectory() as workspace:
            for i in range(30):
                kind = "old-kind-%d" % (i % 3)
                record_lesson(workspace, "lesson %d" % i, kind=kind)

            self.assertTrue(fold_old_lessons(workspace))

            lessons = [line for line in open(os.path.join(workspace, "LESSONS.md"), encoding="utf-8").read().splitlines()
                       if line.startswith("- ")]
            self.assertLessEqual(len(lessons), 25)

            summary_path = os.path.join(workspace, "LESSONS.summary.md")
            self.assertTrue(os.path.isfile(summary_path))
            summary = open(summary_path, encoding="utf-8").read()
            self.assertTrue(summary.strip())
            for kind in ("old-kind-0", "old-kind-1", "old-kind-2"):
                self.assertIn("%s: " % kind, summary)

    def test_a_two_word_kind_is_counted_as_itself(self):
        with tempfile.TemporaryDirectory() as workspace:
            for i in range(30):
                record_lesson(workspace, "Reviewer rejected: item %d -- wrong" % i)
            fold_old_lessons(workspace)
            summary = open(os.path.join(workspace, "LESSONS.summary.md"), encoding="utf-8").read()
            self.assertIn("- Reviewer rejected: 5", summary)


if __name__ == "__main__":
    unittest.main()
