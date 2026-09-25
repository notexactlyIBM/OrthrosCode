"""Tests for relevant_lessons kind-prefix boosting."""

import os
import tempfile
import unittest

from ralph_prompts import relevant_lessons, _lesson_kind


class TestLessonKind(unittest.TestCase):
    def test_extracts_kind_from_line(self):
        line = "- 2026-09-25 reply-cut-off: In `foo` (bar.py), fix it"
        self.assertEqual(_lesson_kind(line), "reply-cut-off")

    def test_multi_word_kind(self):
        line = "- 2026-09-25 Reviewer rejected: In `foo` (bar.py), fix it"
        self.assertEqual(_lesson_kind(line), "Reviewer rejected")

    def test_unrelated_mention_not_matched(self):
        line = "- 2026-09-25 Parked: the reply-cut-off issue was discussed"
        self.assertEqual(_lesson_kind(line), "Parked")


class TestKindBoost(unittest.TestCase):
    def _workspace(self, lessons):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "LESSONS.md"), "w") as f:
            f.write("# Lessons\n\n" + "\n".join(lessons) + "\n")
        return tmp

    def test_kind_match_ranks_above_generic(self):
        lessons = [
            "- 2026-09-25 edit-not-applied: In `record_lesson` (ralph_tools.py), fix it",
            "- 2026-09-25 generic: In `record_lesson` (ralph_tools.py), other issue",
        ]
        ws = self._workspace(lessons)
        task = "In `record_lesson` (ralph_tools.py), do something"
        result = relevant_lessons(ws, task, most=5, last_failure_kind="edit-not-applied")
        self.assertEqual(result[0], lessons[0])

    def test_kind_match_wins_even_with_fewer_identifiers(self):
        lessons = [
            "- 2026-09-25 edit-not-applied: In `foo` (bar.py), simple",
            "- 2026-09-25 generic: In `record_lesson` (ralph_tools.py), "
            "In `foo` (bar.py), In `baz` (qux.py), In `quux` (corge.py), "
            "In `grault` (garply.py), In `waldo` (fred.py), "
            "In `plugh` (xyzzy.py), In `thud` (asdf.py)",
        ]
        ws = self._workspace(lessons)
        task = "In `record_lesson` (ralph_tools.py), In `foo` (bar.py), In `baz` (qux.py), " \
               "In `quux` (corge.py), In `grault` (garply.py), In `waldo` (fred.py), " \
               "In `plugh` (xyzzy.py), In `thud` (asdf.py)"
        result = relevant_lessons(ws, task, most=5, last_failure_kind="edit-not-applied")
        self.assertEqual(result[0], lessons[0])

    def test_no_kind_given_no_boost(self):
        lessons = [
            "- 2026-09-25 edit-not-applied: In `foo` (bar.py), simple",
            "- 2026-09-25 generic: In `record_lesson` (ralph_tools.py), In `foo` (bar.py), "
            "In `baz` (qux.py), In `quux` (corge.py)",
        ]
        ws = self._workspace(lessons)
        task = "In `record_lesson` (ralph_tools.py), In `foo` (bar.py), In `baz` (qux.py), " \
               "In `quux` (corge.py)"
        result = relevant_lessons(ws, task, most=5)
        self.assertEqual(result[0], lessons[1])


if __name__ == "__main__":
    unittest.main()
