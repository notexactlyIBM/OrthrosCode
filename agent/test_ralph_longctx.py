"""Tests for trading time for reach: locate, gists, digest, warming retries.

A fake `ask` stands in for the model: no network, no LM Studio, no sleeping.
"""

import os
import shutil
import tempfile
import unittest

from ralph_common import read_text, write_text
from ralph_digest import digest, inside, parse_request, split_parts
from ralph_gists import GISTS_FILE, read_gists, refresh_gists
from ralph_locate import locate, outline
from ralph_send import attempt_temperature
from ralph_tools import FOUND_FILE, handle_tool_requests


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.a = self.file("alpha.py", '"""Parses things."""\n\n\ndef parse():\n    pass\n')
        self.b = self.file("beta.py", '"""Writes things."""\n\n\nclass Writer:\n    pass\n')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def file(self, name, body):
        path = os.path.join(self.dir, name)
        write_text(path, body)
        return path


class TestLocate(Temp):
    def test_outline_names_what_each_module_defines(self):
        text = outline([self.a, self.b])
        self.assertIn("alpha.py: parse", text)
        self.assertIn("beta.py: Writer", text)

    def test_the_files_the_model_names_are_used(self):
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return "beta.py\nnot_a_file.py\nalpha.py"
        self.assertEqual(locate("make writing safer", [self.a, self.b], ask), [self.b, self.a])
        self.assertIn("make writing safer", asked[0])

    def test_no_model_no_guess(self):
        self.assertEqual(locate("x", [self.a, self.b], None), [])
        self.assertEqual(locate("x", [self.a, self.b], lambda p: "no idea"), [])


class TestGists(Temp):
    def test_the_model_writes_gists_up_to_the_limit_and_the_rest_wait(self):
        calls = []

        def ask(prompt):
            calls.append(prompt)
            return "It does a thing.\nMain: one function."
        written, left = refresh_gists(self.dir, [self.a, self.b], ask, limit=1)
        self.assertEqual((written, left, len(calls)), (1, 1, 1))
        gists = read_gists(os.path.join(self.dir, GISTS_FILE))
        self.assertEqual(sorted(gists), ["alpha.py", "beta.py"])
        self.assertTrue(gists["beta.py"][1])                 # provisional
        self.assertEqual(gists["beta.py"][2], "Writes things.")
        written, left = refresh_gists(self.dir, [self.a, self.b], ask, limit=1)
        self.assertEqual((written, left), (2, 0))

    def test_a_changed_module_is_summed_up_again(self):
        ask = lambda prompt: "Gist."                          # noqa: E731
        refresh_gists(self.dir, [self.a, self.b], ask, limit=5)
        write_text(self.a, read_text(self.a) + "\n\ndef more():\n    pass\n")
        calls = []
        refresh_gists(self.dir, [self.a, self.b], lambda p: calls.append(p) or "New.", limit=5)
        self.assertEqual(len(calls), 1)
        self.assertIn("File: alpha.py", calls[0])

    def test_without_a_model_the_docstrings_serve(self):
        self.assertEqual(refresh_gists(self.dir, [self.a, self.b], None), (0, 2))
        self.assertIn("Parses things.", read_text(os.path.join(self.dir, GISTS_FILE)))


class TestDigest(Temp):
    def test_parts_are_read_in_order_with_notes_carried(self):
        big = self.file("big.log", "".join("line %d\n" % i for i in range(3000)))
        seen = []

        def ask(prompt):
            seen.append(prompt)
            if prompt.startswith("Question:"):
                return "The answer."
            return "notes after part %d" % len(seen)
        answer, parts, whole = digest(big, "what happened?", ask, most=12)
        self.assertEqual((answer, whole), ("The answer.", True))
        self.assertGreater(parts, 0)
        self.assertEqual(len(seen), parts + 1)
        if parts > 1:
            self.assertIn("notes after part 1", seen[1])

    def test_a_huge_file_is_cut_to_the_most_parts(self):
        parts, whole = split_parts("x" * 100 + "\n" * 1 + ("y" * 60 + "\n") * 20000, most=3)
        self.assertEqual((len(parts), whole), (3, False))

    def test_request_forms_and_folder_bounds(self):
        self.assertEqual(parse_request("big.log -- why?"), ("big.log", "why?"))
        self.assertEqual(parse_request("`big.log` | why?"), ("big.log", "why?"))
        self.assertEqual(inside(self.dir, "alpha.py"), os.path.realpath(self.a))
        self.assertEqual(inside(self.dir, "../../etc/passwd"), "")

    def test_the_tool_request_is_answered_in_found(self):
        notes = self.file("tasks.md", "- [ ] x\nDIGEST: alpha.py -- what does it parse?\n")
        handled = handle_tool_requests(self.dir, notes, "python", ask=lambda p: "It parses.")
        self.assertIn("DIGEST", handled)
        self.assertIn("It parses.", read_text(os.path.join(self.dir, FOUND_FILE)))
        self.assertIn("*Digested*: alpha.py", read_text(notes))


class TestWarmingRetries(unittest.TestCase):
    def test_each_try_is_warmer_up_to_the_brainstorm_setting(self):
        temps = [attempt_temperature(n, 0.2, 0.85) for n in (1, 2, 3, 4, 5)]
        self.assertEqual(temps, [0.2, 0.45, 0.7, 0.85, 0.85])


if __name__ == "__main__":
    unittest.main()
