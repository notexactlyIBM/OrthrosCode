import unittest

from rle import decode, encode


class TestEncode(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(encode(""), "")

    def test_no_runs(self):
        self.assertEqual(encode("XYZ"), "XYZ")

    def test_runs(self):
        self.assertEqual(encode("WWWWBBBW"), "4W3BW")

    def test_long_run(self):
        self.assertEqual(encode("A" * 12 + "B"), "12AB")

    def test_spaces(self):
        self.assertEqual(encode("  hsqq qww  "), "2 hs2q q2w2 ")


class TestDecode(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(decode(""), "")

    def test_multi_digit(self):
        self.assertEqual(decode("12WB3C"), "W" * 12 + "BCCC")

    def test_round_trip(self):
        for text in ("zzz ZZ  zZ", "  hello  ", "aabbbcccc", "x"):
            self.assertEqual(decode(encode(text)), text)
