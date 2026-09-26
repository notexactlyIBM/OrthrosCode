import unittest

from series import largest_product, slices


class TestSlices(unittest.TestCase):
    def test_slices(self):
        self.assertEqual(slices("49142", 3), ["491", "914", "142"])
        self.assertEqual(slices("1", 1), ["1"])
        self.assertEqual(slices("777", 3), ["777"])

    def test_bad(self):
        for series, length in (("12", 3), ("", 1), ("123", 0), ("123", -1)):
            with self.assertRaises(ValueError):
                slices(series, length)


class TestProduct(unittest.TestCase):
    def test_product(self):
        self.assertEqual(largest_product("63915", 3), 162)
        self.assertEqual(largest_product("0123456789", 2), 72)

    def test_zeroes(self):
        self.assertEqual(largest_product("99099", 3), 0)

    def test_empty_product(self):
        self.assertEqual(largest_product("123", 0), 1)

    def test_bad(self):
        for series, length in (("12", 3), ("1234a5", 2), ("123", -1)):
            with self.assertRaises(ValueError):
                largest_product(series, length)
