import unittest

from anagram import find_anagrams


class TestAnagrams(unittest.TestCase):
    def test_none(self):
        self.assertEqual(find_anagrams("diaper", ["hello", "world", "zombies", "pants"]), [])

    def test_one(self):
        self.assertEqual(find_anagrams("listen", ["enlists", "google", "inlets", "banana"]),
                         ["inlets"])

    def test_several_in_order(self):
        self.assertEqual(find_anagrams("allergy", ["gallery", "ballerina", "regally",
                                                   "clergy", "largely", "leading"]),
                         ["gallery", "regally", "largely"])

    def test_case_insensitive(self):
        self.assertEqual(find_anagrams("Orchestra", ["cashregister", "Carthorse", "radishes"]),
                         ["Carthorse"])

    def test_not_itself(self):
        self.assertEqual(find_anagrams("BANANA", ["banana", "Banana", "BANANA"]), [])

    def test_same_letters_different_counts(self):
        self.assertEqual(find_anagrams("tapper", ["patter"]), [])

    def test_subset_is_not_anagram(self):
        self.assertEqual(find_anagrams("good", ["dog", "goody"]), [])
