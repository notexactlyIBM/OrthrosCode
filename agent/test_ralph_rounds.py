"""Tests for choosing a round's files and reading what aider said."""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

import ralph_rounds
from ralph_common import write_text
from ralph_rounds import build_round_command, files_for_refill, files_for_task, run_round


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def file(self, name, body):
        path = os.path.join(self.dir, name)
        write_text(path, body)
        return path


class TestFilesForTask(Temp):
    def setUp(self):
        super().setUp()
        self.a = self.file("alpha.py", "class Parser:\n    def read(self):\n        pass\n")
        self.b = self.file("beta.py", "def helper():\n    pass\n")
        self.files = [self.a, self.b]

    def test_names_a_class(self):
        self.assertEqual(files_for_task("In `Parser.read`, strip it", self.files), [self.a])

    def test_names_a_function(self):
        self.assertEqual(files_for_task("In `helper`, return 1", self.files), [self.b])

    def test_prefix_is_not_a_match(self):
        self.assertEqual(files_for_task("In `help`, x", self.files), self.files)

    def test_names_a_file(self):
        self.assertEqual(files_for_task("Add `new_thing` to beta.py", self.files), [self.b])

    def test_nothing_named_and_too_big_sends_nothing(self):
        old = ralph_rounds.FALLBACK_TOKENS
        ralph_rounds.FALLBACK_TOKENS = 1
        try:
            self.assertEqual(files_for_task("Write SKILLS.md", self.files), [])
        finally:
            ralph_rounds.FALLBACK_TOKENS = old


class TestFilesForRefill(Temp):
    def setUp(self):
        super().setUp()
        self.a = self.file("alpha.py", "class Parser:\n    def read(self):\n        pass\n")
        self.b = self.file("beta.py", "def helper():\n    pass\n")

    def test_zero_budget_sends_nothing(self):
        old = ralph_rounds.FALLBACK_TOKENS
        ralph_rounds.FALLBACK_TOKENS = 0
        try:
            self.assertEqual(files_for_refill("anything", [self.a, self.b]), [])
        finally:
            ralph_rounds.FALLBACK_TOKENS = old


class TestRunRound(Temp):
    def run_fake(self, *lines):
        script = self.file("fake.py", "".join("print(%r)\n" % l for l in lines))
        with contextlib.redirect_stdout(io.StringIO()):
            return run_round([sys.executable, script], self.dir, os.environ.copy(), 60)

    def test_tokens_and_edits(self):
        r = self.run_fake("Applied edit to x.py", "Tokens: 2.5k sent, 1k received.")
        self.assertTrue(r.ran)
        self.assertEqual((r.sent, r.got, r.applied, r.symptom), (2500, 1000, 1, ""))

    def test_engine_death(self):
        r = self.run_fake("litellm.APIConnectionError: Connection refused")
        self.assertEqual(r.symptom, "enginedied")

    def test_survived_engine_error_is_not_death(self):
        r = self.run_fake("litellm.APIConnectionError: Connection refused",
                          "Tokens: 1k sent, 200 received.")
        self.assertEqual((r.symptom, r.shrugged_off), ("", 1))

    def test_full_window(self):
        r = self.run_fake("Your request hit a token limit",
                          "Total tokens: ~30,000 of 32,768 -- possibly exhausted")
        self.assertEqual(r.symptom, "context")
        self.assertTrue(r.crowded)

    def test_prompt_too_big_is_not_engine_death(self):
        # Verbatim shape from the 2026-09-23 logs: the connection-error line
        # comes first, and used to mark the round as a dead engine.
        r = self.run_fake(
            "litellm.APIConnectionError: APIConnectionError: OpenAIException - Engine",
            'protocol predict request returned 400: {"error":{"code":400,"message":"request',
            "(32958 tokens) exceeds the available context size (32768 tokens), try",
            "Retrying in 0.2 seconds...",
            "litellm.APIConnectionError: APIConnectionError: OpenAIException - Engine")
        self.assertEqual((r.symptom, r.refused, r.overstuffed), ("context", True, True))

    def test_guard_refusal_is_a_refused_prompt(self):
        r = self.run_fake("Orthros guard: prompt too big for the context window: ~40000 of "
                          "32768 tokens. Not sending it.")
        self.assertTrue(r.refused)

    def test_failed_edit(self):
        r = self.run_fake("The SEARCH/REPLACE block failed to match")
        self.assertEqual(r.failed, 1)


class TestBuildRoundCommand(Temp):
    def test_only_existing_files(self):
        notes = self.file("tasks.md", "- [ ] x\n")
        real = self.file("a.py", "")
        cmd = build_round_command(["aider"], "prompt.md", notes, [real],
                                  [os.path.join(self.dir, "missing.md")])
        self.assertIn(real, cmd)
        self.assertNotIn("--read", cmd)


if __name__ == "__main__":
    unittest.main()
