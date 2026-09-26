import unittest

from pangram import is_pangram, missing_letters


class TestPangram(unittest.TestCase):
    def test_empty(self):
        self.assertFalse(is_pangram(""))

    def test_pangram(self):
        self.assertTrue(is_pangram("The quick brown fox jumps over the lazy dog"))

    def test_missing_x(self):
        self.assertFalse(is_pangram("a quick movement of the enemy will jeopardize five gunboats"))

    def test_mixed_case_and_digits(self):
        self.assertTrue(is_pangram("Five quacking Zephyrs jolt my wax bed 42"))

    def test_missing_letters(self):
        self.assertEqual(missing_letters("abc xyz"), "defghijklmnopqrstuvw")
        self.assertEqual(missing_letters("The quick brown fox jumps over the lazy dog"), "")
