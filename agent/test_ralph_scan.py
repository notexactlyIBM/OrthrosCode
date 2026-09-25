"""Tests for catching bad edits: the no-token checks and the second look.

No model, no network: the reviewer's requests are answered by a script.
"""

import os
import shutil
import sys
import tempfile
import unittest

import supervisor_aider
from ralph_common import read_text, write_text
from ralph_scan import (baseline, call_mismatches, diff_findings, main_block_last,
                        marker_findings, put_main_last, scan)
from ralph_send import named_code, review_context


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


class TestMainLast(Temp):
    TESTS = ('import unittest\n\n\nclass TestA(unittest.TestCase):\n    def test_a(self):\n'
             '        pass\n\n\nif __name__ == "__main__":\n    unittest.main()\n')
    ADDED = "\n\nclass TestB(unittest.TestCase):\n    def test_b(self):\n        pass\n"

    def raw(self, name, body):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(body)
        return path

    def test_a_class_added_below_the_block_is_moved_above_it(self):
        path = self.raw("test_game.py", self.TESTS + self.ADDED)
        diff = "+++ b/test_game.py\n+class TestB(unittest.TestCase):\n"
        self.assertEqual(put_main_last([path, self.lib], diff), [path])
        body = read_text(path)
        self.assertTrue(body.rstrip().endswith("unittest.main()"))
        self.assertLess(body.index("class TestB"), body.index("__main__"))
        self.assertEqual(body.count("__main__"), 1)
        compile(body, path, "exec")

    def test_a_second_copy_of_the_block_is_dropped(self):
        path = self.raw("test_game.py", self.TESTS.replace(
            "\n\nclass TestA", '\n\nif __name__ == "__main__":\n    unittest.main()\n\n\nclass TestA'))
        self.assertTrue(main_block_last(path))
        self.assertEqual(read_text(path).count("__main__"), 1)

    def test_line_endings_are_kept(self):
        for eol in ("\n", "\r\n"):
            path = self.raw("test_game.py", (self.TESTS + self.ADDED).replace("\n", eol))
            self.assertTrue(main_block_last(path))
            with open(path, "rb") as handle:
                text = handle.read().decode("utf-8")
            self.assertEqual(text.count("\r\n"), text.count("\n") if eol == "\r\n" else 0)

    def test_blocks_that_differ_are_left_for_a_reader(self):
        path = self.raw("test_game.py", self.TESTS + '\n\nif __name__ == "__main__":\n'
                                                     '    unittest.main(verbosity=2)\n')
        self.assertFalse(main_block_last(path))

    def test_only_test_files_the_round_touched(self):
        path = self.raw("test_game.py", self.TESTS + self.ADDED)
        self.assertEqual(put_main_last([path], "+++ b/lib.py\n+x = 1\n"), [])
        self.assertEqual(put_main_last([path], "NEW FILE test_game.py:\nimport unittest\n"), [path])

    def test_a_block_already_last_is_not_touched(self):
        self.assertFalse(main_block_last(self.raw("test_game.py", self.TESTS)))
        self.assertFalse(main_block_last(self.lib))


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

    def test_what_the_diff_cannot_show_reaches_all_three_reads(self):
        self.script("VERDICT: ACCEPT\nREASON: fine",
                    "BUG: line 2 calls re.finditer but re is never imported",
                    "VERDICT: ACCEPT\nREASON: re is imported in lines the diff does not show")
        verdict, _ = supervisor_aider.review_change("area", "+x", context="\nre is imported\n")
        self.assertEqual(verdict, "accept")
        self.assertEqual(len(self.asked), 3)
        self.assertTrue(all("re is imported" in prompt for prompt in self.asked))


class TestReviewContext(Temp):
    def test_the_code_an_item_names_is_shown_as_it_stands(self):
        found = named_code("In `area` (lib.py), default the height to 1", [self.app, self.lib])
        self.assertEqual([(os.path.basename(p), n) for p, n, _ in found], [("lib.py", "area")])
        self.assertIn("return width * height", found[0][2])

    def test_a_method_is_found_inside_its_class(self):
        path = self.file("shape.py", "class Shape:\n    def grow(self, by):\n        return by * 2\n")
        found = named_code("In `Shape.grow`, double it", [path])
        self.assertEqual(found[0][1], "Shape.grow")
        self.assertTrue(found[0][2].lstrip().startswith("def grow"))

    def test_nothing_named_shows_nothing_and_the_limit_holds(self):
        self.assertEqual(named_code("Tidy the README", [self.lib]), [])
        self.assertEqual(named_code("In `area`, round it", [self.lib], limit=10), [])

    def test_pyflakes_is_only_claimed_when_it_ran(self):
        self.assertIn("pyflakes", review_context("In `area`, x", [self.lib], linted=True))
        text = review_context("In `area`, x", [self.lib], linted=False)
        self.assertNotIn("pyflakes", text)
        self.assertIn("def area", text)


if __name__ == "__main__":
    sys.exit(unittest.main())
