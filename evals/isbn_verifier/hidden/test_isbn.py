import unittest

from isbn import is_valid


class TestIsbn(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_valid("3598215088"))

    def test_valid_with_dashes(self):
        self.assertTrue(is_valid("3-598-21508-8"))

    def test_check_digit_x(self):
        self.assertTrue(is_valid("3-598-21507-X"))

    def test_invalid_check_digit(self):
        self.assertFalse(is_valid("3-598-21508-9"))

    def test_x_only_at_the_end(self):
        self.assertFalse(is_valid("3-598-2X507-9"))

    def test_too_long(self):
        self.assertFalse(is_valid("3598215078X"))

    def test_too_short(self):
        self.assertFalse(is_valid("3-598-21507"))

    def test_empty(self):
        self.assertFalse(is_valid(""))

    def test_letters(self):
        self.assertFalse(is_valid("359821507A"))

    def test_all_zeros_is_valid(self):
        self.assertTrue(is_valid("0000000000"))
