"""Tests for catching bad edits: the no-token checks and the second look.

No model, no network: the reviewer's requests are answered by a script.
"""

import os
import shutil
import sys
import tempfile
import unittest

import supervisor_aider
from ralph_common import write_text
from ralph_scan import baseline, call_mismatches, diff_findings, marker_findings, scan


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.lib = self.file("lib.py", "def area(width, height=1):\n    return width * height\n")
        self.app = self.file("app.py", "from lib import area\n\n\ndef main():\n"
                                       "    return area(2, 3)\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def file(self, name, body):
        path = os.path.join(self.dir, name)
        write_text(path, body)
        return path


class TestCalls(Temp):
    def test_a_changed_signature_breaks_a_caller_in_another_file(self):
        before = call_mismatches([self.lib, self.app])
        self.assertEqual(before, set())
        write_text(self.lib, "def area(width):\n    return width * width\n")
        after = call_mismatches([self.lib, self.app])
        self.assertEqual(after, {"app.py: area() given 2 positional arguments, takes at most 1"})

    def test_unknown_and_missing_keywords(self):
        write_text(self.app, "from lib import area\n\n\ndef main():\n    return area(depth=2)\n")
        found = call_mismatches([self.lib, self.app])
        self.assertIn("app.py: area() has no argument called depth", found)
        write_text(self.app, "from lib import area\n\n\ndef main():\n    return area()\n")
        self.assertIn("app.py: area() needs 1 arguments, given 0",
                      call_mismatches([self.lib, self.app]))

    def test_a_library_function_of_the_same_name_is_not_ours(self):
        write_text(self.app, "from os.path import join\n\n\ndef main():\n"
                             "    return join('a', 'b', 'c')\n")
        self.file("mine.py", "def join(one):\n    return one\n")
        self.assertEqual(call_mismatches([self.lib, self.app,
                                          os.path.join(self.dir, "mine.py")]), set())

    def test_star_arguments_are_left_alone(self):
        write_text(self.app, "from lib import area\n\n\ndef main(*a):\n    return area(*a)\n")
        self.assertEqual(call_mismatches([self.lib, self.app]), set())


class TestDiff(unittest.TestCase):
    def test_a_placeholder_instead_of_code_is_rejected(self):
        diff = ("+++ b/game.py\n-    def draw(self):\n-        blit()\n"
                "+    # ... rest of the code unchanged\n")
        kinds = [k for k, _ in diff_findings(diff, "In `Game.draw`, x")]
        self.assertEqual(kinds, ["reject"])

    def test_deleted_tests_are_rejected(self):
        diff = "+++ b/test_game.py\n-    def test_draw(self):\n-        self.assertTrue(x)\n"
        self.assertIn("test(s) deleted", diff_findings(diff, "In `draw`, speed up")[0][1])

    def test_a_new_test_is_fine(self):
        diff = "+++ b/test_game.py\n+    def test_more(self):\n+        self.assertTrue(x)\n"
        self.assertEqual(diff_findings(diff, "Add a test"), [])

    def test_a_big_unexplained_deletion_is_a_warning(self):
        diff = "+++ b/big.py\n" + "-x = 1\n" * 40 + "+y = 2\n"
        self.assertEqual(diff_findings(diff, "In `other`, fix it")[0][0], "warn")

    def test_an_ordinary_comment_is_not_a_placeholder(self):
        diff = "+++ b/a.py\n-x = 1\n+# keep the width in pixels\n+x = 2\n"
        self.assertEqual(diff_findings(diff, "x"), [])


class TestScan(Temp):
    def test_conflict_markers(self):
        write_text(self.lib, "<<<<<<< SEARCH\ndef area(w):\n=======\n")
        self.assertEqual(marker_findings([self.lib])[0][0], "reject")

    def test_only_what_the_round_added_counts(self):
        before = baseline([self.lib, self.app])
        write_text(self.lib, "def area(width):\n    return width * width\n")
        found = scan([self.lib, self.app], "", "In `area`, square it", before)
        self.assertEqual([k for k, _ in found], ["reject"])
        self.assertEqual(scan([self.lib, self.app], "", "x", baseline([self.lib, self.app])), [])

    def test_lint_regressions_when_pyflakes_is_there(self):
        before = baseline([self.lib])
        if before["lint"] is None:
            self.skipTest("pyflakes is not installed here")
        write_text(self.lib, "def area(width, height=1):\n    return widht * height\n")
        found = scan([self.lib], "", "x", before)
        self.assertTrue(any(k == "reject" and "undefined name" in m for k, m in found))


class TestSecondLook(unittest.TestCase):
    def setUp(self):
        self.real = supervisor_aider._chat
        self.passes = supervisor_aider.REVIEW_PASSES
        supervisor_aider.REVIEW_PASSES = 2
        self.asked = []

    def tearDown(self):
        supervisor_aider._chat = self.real
        supervisor_aider.REVIEW_PASSES = self.passes

    def script(self, *replies):
        replies = list(replies)

        def chat(prompt, max_tokens, timeout, temperature=0.1):
            self.asked.append(prompt)
            return replies.pop(0), "stop"
        supervisor_aider._chat = chat

    def test_a_confirmed_bug_rejects_a_change_the_first_review_kept(self):
        self.script("VERDICT: ACCEPT\nREASON: fine",
                    "BUG: line 3 returns width twice instead of width * height",
                    "VERDICT: REJECT\nREASON: the claim is right, height is ignored")
        verdict, why = supervisor_aider.review_change("area", "+x")
        self.assertEqual(verdict, "reject")
        self.assertIn("second look", why)
        self.assertEqual(len(self.asked), 3)

    def test_an_unconfirmed_bug_keeps_the_change(self):
        self.script("VERDICT: ACCEPT\nREASON: fine", "BUG: the variable name could be clearer here",
                    "VERDICT: ACCEPT\nREASON: that is style, not a fault")
        self.assertEqual(supervisor_aider.review_change("area", "+x")[0], "accept")

    def test_none_found_keeps_it_in_two_requests(self):
        self.script("VERDICT: ACCEPT\nREASON: fine", "NONE")
        self.assertEqual(supervisor_aider.review_change("area", "+x")[0], "accept")
        self.assertEqual(len(self.asked), 2)

    def test_the_automatic_findings_reach_the_reviewer(self):
        self.script("VERDICT: REJECT\nREASON: it deletes the parser")
        supervisor_aider.review_change("area", "+x", notes=["big.py: 40 lines removed"])
        self.assertIn("big.py: 40 lines removed", self.asked[0])


if __name__ == "__main__":
    sys.exit(unittest.main())
