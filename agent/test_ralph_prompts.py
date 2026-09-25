"""Tests for relevant_lessons: ranking LESSONS.md lines by shared identifiers."""

import os
import shutil
import tempfile
import unittest

from ralph_common import write_text
from ralph_prompts import compose_refill_prompt, relevant_lessons


class TestRelevantLessons(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        lessons = os.path.join(self.dir, "LESSONS.md")
        write_text(lessons,
            "# Lessons\n"
            "- 2026-09-24 Reviewer rejected: In `record_lesson` (ralph_tools.py), something\n"
            "- 2026-09-24 Reviewer rejected: In `gui_state` (gui.py), something else\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_lesson_naming_the_function_ranks_above_one_naming_only_gui(self):
        task = "In `record_lesson` (ralph_tools.py), trim old lines"
        ranked = relevant_lessons(self.dir, task, most=5)
        self.assertIn("record_lesson", ranked[0])

    def test_a_lesson_naming_the_file_ranks_above_one_naming_only_gui(self):
        task = "In ralph_tools.py, add a helper"
        ranked = relevant_lessons(self.dir, task, most=5)
        self.assertIn("ralph_tools.py", ranked[0])

    def test_ordinary_words_do_not_score(self):
        # "the" and "old" are not identifiers; they must not create a match.
        task = "the old thing"
        ranked = relevant_lessons(self.dir, task, most=5)
        # No identifiers extracted -> falls back to recency (last `most` lines).
        self.assertEqual(len(ranked), 2)

    def test_kind_matching_lesson_outranks_higher_scoring_unrelated(self):
        lessons = os.path.join(self.dir, "LESSONS.md")
        write_text(lessons,
            "# Lessons\n"
            "- 2026-09-25 reply-cut-off: In `foo_bar` (mod.py), the reply was cut off\n"
            "- 2026-09-25 Reviewer rejected: In `foo_bar` (mod.py), `baz_qux`, `qux_baz`, `foo_bar` -- high score\n")
        # Task matches more identifiers in the unrelated line (score 4 vs 2),
        # but the kind tier must put the reply-cut-off lesson first.
        task = "In `foo_bar` (mod.py), `baz_qux`, `qux_baz`, fix it"
        ranked = relevant_lessons(self.dir, task, most=5, last_failure_kind="reply-cut-off")
        self.assertIn("reply-cut-off", ranked[0])


class TestRefillLessons(unittest.TestCase):
    def test_at_most_five_lessons_under_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Write a 40-line LESSONS.md
            lessons_path = os.path.join(tmp, "LESSONS.md")
            lines = ["# Lessons", ""]
            for i in range(40):
                lines.append("- 2026-09-24 Reviewer rejected: In `func_%d` (mod_%d.py), "
                             "do something -- a second look found: issue %d" % (i, i, i))
            with open(lessons_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            # Write a minimal notes file
            notes_path = os.path.join(tmp, "NOTES.md")
            with open(notes_path, "w", encoding="utf-8") as f:
                f.write("# Tasks\n\n- [ ] In `func_0` (mod_0.py), do something.\n")

            # Build a refill prompt
            text, label, mode, milestone = compose_refill_prompt(notes_path, 1)

            # Find the "Lessons that fit" section and count lesson lines
            if "# Lessons that fit" in text:
                section = text.split("# Lessons that fit", 1)[1]
                # Cut at the next heading or end
                for marker in ("\n# ", "\n## "):
                    if marker in section:
                        section = section.split(marker, 1)[0]
                        break
                lesson_lines = [l for l in section.splitlines() if l.startswith("- ")]
                self.assertLessEqual(len(lesson_lines), 5,
                                     "Expected at most 5 lesson lines, got %d" % len(lesson_lines))
            else:
                # No lessons heading is acceptable if LESSONS.md has no matching lines,
                # but with 40 lines it should appear.
                self.fail("Expected '# Lessons that fit' heading in refill prompt")


if __name__ == "__main__":
    unittest.main()
