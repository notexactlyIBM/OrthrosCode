import unittest

from acronym import abbreviate


class TestAcronym(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(abbreviate("Portable Network Graphics"), "PNG")

    def test_lowercase(self):
        self.assertEqual(abbreviate("Ruby on Rails"), "ROR")

    def test_hyphen(self):
        self.assertEqual(abbreviate("Complementary metal-oxide semiconductor"), "CMOS")

    def test_punctuation(self):
        self.assertEqual(abbreviate("Halley's Comet"), "HC")
        self.assertEqual(abbreviate("The Road _Not_ Taken"), "TRNT")

    def test_extra_spaces_and_dashes(self):
        self.assertEqual(abbreviate("Rolling On The Floor Laughing So Hard - That"), "ROTFLSHT")
