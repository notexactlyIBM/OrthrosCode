import unittest

from readings import parse, stats


class TestParse(unittest.TestCase):
    def test_one(self):
        self.assertEqual(parse("07:30 18.5"), [(450, 18.5)])

    def test_skips_bad_lines(self):
        text = "07:30 18.5\nnonsense\n25:00 3\n08:61 4\n09:00 warm\n\n10:00 -2"
        self.assertEqual(parse(text), [(450, 18.5), (600, -2.0)])

    def test_whitespace_around(self):
        self.assertEqual(parse("  00:00   1  \n"), [(0, 1.0)])


class TestStats(unittest.TestCase):
    def test_odd(self):
        s = stats("00:00 10\n01:00 40\n02:00 20")
        self.assertEqual((s["min"], s["max"], s["median"]), (10, 40, 20))
        self.assertEqual(s["mean"], 23.33)

    def test_even_median(self):
        self.assertEqual(stats("00:00 1\n00:01 2\n00:02 3\n00:03 10")["median"], 2.5)

    def test_ignores_bad(self):
        self.assertEqual(stats("x\n12:00 5\n")["max"], 5)

    def test_nothing_valid(self):
        with self.assertRaises(ValueError):
            stats("bad\n")
        with self.assertRaises(ValueError):
            stats("")
