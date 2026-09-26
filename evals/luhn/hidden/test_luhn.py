import unittest

from luhn import valid


class TestLuhn(unittest.TestCase):
    def test_single_digit(self):
        self.assertFalse(valid("1"))
        self.assertFalse(valid("0"))

    def test_zero_with_space(self):
        self.assertTrue(valid(" 0 0 "))

    def test_valid_card(self):
        self.assertTrue(valid("4539 3195 0343 6467"))

    def test_invalid_card(self):
        self.assertFalse(valid("8273 1232 7352 0569"))

    def test_simple(self):
        self.assertTrue(valid("059"))
        self.assertTrue(valid("091"))
        self.assertFalse(valid("58"))

    def test_nine_after_doubling(self):
        self.assertTrue(valid("095 245 88"))

    def test_non_digits(self):
        self.assertFalse(valid("055a 444 285"))
        self.assertFalse(valid("055-444-285"))
        self.assertFalse(valid(":9"))
