"""New items that repeat work already done, parked or listed are dropped."""

import os
import tempfile
import unittest

from ralph_common import read_text, write_text
from ralph_tasks import drop_repeats, open_tasks


class TestDropRepeats(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.notes = os.path.join(self.dir, "tasks.md")

    def test_a_near_copy_of_done_work_is_dropped(self):
        write_text(self.notes, "# Tasks\n\n- [x] In `add` (calc.py), handle None. Done when: "
                               "add(None, 1) raises TypeError.\n- [ ] Keep this\n")
        before = open_tasks(self.notes)
        with open(self.notes, "a") as h:
            h.write("- [ ] In `add` (calc.py), handle None -- Done when: add(None, 2) raises\n"
                    "- [ ] In `sub` (calc.py), handle None. Done when: sub(None, 1) raises.\n")
        dropped = drop_repeats(self.notes, before)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(open_tasks(self.notes), [
            "Keep this", "In `sub` (calc.py), handle None. Done when: sub(None, 1) raises."])

    def test_done_work_in_the_archive_counts(self):
        write_text(self.notes, "# Tasks\n\n")
        write_text(os.path.join(self.dir, "DONE.md"), "- [x] Add a `--quiet` flag to cli.py\n")
        with open(self.notes, "a") as h:
            h.write("- [ ] Add a `--quiet` flag to cli.py.\n")
        self.assertEqual(len(drop_repeats(self.notes, [])), 1)

    def test_a_repeat_within_the_same_refill_and_of_parked_work(self):
        write_text(self.notes, "# Tasks\n\n- [!] Rewrite the parser in parse.py\n"
                               "- [ ] Cache results in `lookup`\n- [ ] Cache the results in `lookup`\n"
                               "- [ ] Rewrite the parser in parse.py\n")
        dropped = drop_repeats(self.notes, [])
        self.assertEqual([d for d, _ in dropped], ["Cache the results in `lookup`",
                                                   "Rewrite the parser in parse.py"])
        self.assertIn("- [!] Rewrite the parser", read_text(self.notes))

    def test_items_that_were_there_before_are_left_alone(self):
        write_text(self.notes, "# Tasks\n\n- [x] Speed up `scan`\n- [ ] Speed up `scan`\n")
        self.assertEqual(drop_repeats(self.notes, ["Speed up `scan`"]), [])

    def test_different_work_on_the_same_function_stays(self):
        write_text(self.notes, "# Tasks\n\n- [x] In `add` (calc.py), handle None\n"
                               "- [ ] In `add` (calc.py), accept strings of digits\n")
        self.assertEqual(drop_repeats(self.notes, []), [])


if __name__ == "__main__":
    unittest.main()
