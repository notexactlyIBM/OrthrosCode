import unittest

from roman import from_roman, to_roman


class TestRoman(unittest.TestCase):
    def test_small(self):
        self.assertEqual([to_roman(n) for n in (1, 3, 4, 9, 14, 40)],
                         ["I", "III", "IV", "IX", "XIV", "XL"])

    def test_large(self):
        self.assertEqual(to_roman(1994), "MCMXCIV")
        self.assertEqual(to_roman(3999), "MMMCMXCIX")

    def test_to_roman_refuses(self):
        for bad in (0, -1, 4000, 2.5, "7"):
            with self.assertRaises(ValueError):
                to_roman(bad)

    def test_from_roman(self):
        self.assertEqual(from_roman("MCMXCIV"), 1994)
        self.assertEqual(from_roman("mcmxciv"), 1994)

    def test_from_roman_refuses(self):
        for bad in ("", "IIII", "IM", "ABC", "VV", "IC"):
            with self.assertRaises(ValueError):
                from_roman(bad)

    def test_round_trip(self):
        for n in range(1, 4000):
            self.assertEqual(from_roman(to_roman(n)), n)
