import unittest

from wrap import wrap


class TestWrap(unittest.TestCase):
    def test_fits(self):
        self.assertEqual(wrap("hello world", 20), ["hello world"])

    def test_two_lines(self):
        self.assertEqual(wrap("the quick brown fox", 10), ["the quick", "brown fox"])

    def test_exact_width(self):
        self.assertEqual(wrap("abc def", 7), ["abc def"])
        self.assertEqual(wrap("abc def", 6), ["abc", "def"])

    def test_whitespace(self):
        self.assertEqual(wrap("  a\n\tb  ", 10), ["a b"])

    def test_empty(self):
        self.assertEqual(wrap("", 5), [])
        self.assertEqual(wrap("   ", 5), [])

    def test_long_word(self):
        self.assertEqual(wrap("a extraordinary b", 5), ["a", "extraordinary", "b"])

    def test_bad_width(self):
        with self.assertRaises(ValueError):
            wrap("a", 0)

    def test_greedy(self):
        text = "aaa bb cc ddddd e"
        self.assertEqual(wrap(text, 6), ["aaa bb", "cc", "ddddd", "e"])
