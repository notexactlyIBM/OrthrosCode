import unittest

from words import count_words


class TestCountWords(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(count_words("one fish two fish"), {"one": 1, "fish": 2, "two": 1})

    def test_case(self):
        self.assertEqual(count_words("Go go GO"), {"go": 3})

    def test_punctuation(self):
        self.assertEqual(count_words("car: carpet as java: javascript!!&@$%^&"),
                         {"car": 1, "carpet": 1, "as": 1, "java": 1, "javascript": 1})

    def test_apostrophes(self):
        self.assertEqual(count_words("'Hello,' she said. Don't!"),
                         {"hello": 1, "she": 1, "said": 1, "don't": 1})

    def test_numbers(self):
        self.assertEqual(count_words("1 2 2"), {"1": 1, "2": 2})

    def test_blank(self):
        self.assertEqual(count_words("  "), {})
        self.assertEqual(count_words(""), {})

    def test_separators(self):
        self.assertEqual(count_words("one,two\nthree\tone"), {"one": 2, "two": 1, "three": 1})
