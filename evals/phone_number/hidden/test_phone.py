import unittest

from phone import PhoneNumber


class TestPhone(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(PhoneNumber("(223) 456-7890").number, "2234567890")
        self.assertEqual(PhoneNumber("223.456.7890").number, "2234567890")

    def test_country_code(self):
        self.assertEqual(PhoneNumber("+1 (613)-995-0253").number, "6139950253")
        self.assertEqual(PhoneNumber("12234567890").number, "2234567890")

    def test_wrong_country_code(self):
        with self.assertRaises(ValueError):
            PhoneNumber("22234567890")

    def test_wrong_length(self):
        for text in ("123456789", "321234567890"):
            with self.assertRaises(ValueError):
                PhoneNumber(text)

    def test_letters_and_punctuation(self):
        for text in ("523-abc-7890", "523-@:!-7890"):
            with self.assertRaises(ValueError):
                PhoneNumber(text)

    def test_area_and_exchange_codes(self):
        for text in ("(023) 456-7890", "(123) 456-7890", "(223) 056-7890", "(223) 156-7890"):
            with self.assertRaises(ValueError):
                PhoneNumber(text)

    def test_area_code(self):
        self.assertEqual(PhoneNumber("2234567890").area_code, "223")

    def test_pretty(self):
        self.assertEqual(PhoneNumber("2234567890").pretty(), "(223)-456-7890")
        self.assertEqual(PhoneNumber("1 223 456 7890 ").pretty(), "(223)-456-7890")
