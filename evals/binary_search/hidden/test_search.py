import unittest

from search import find


class Counting(list):
    reads = 0

    def __getitem__(self, i):
        Counting.reads += 1
        return list.__getitem__(self, i)


class TestFind(unittest.TestCase):
    def test_single(self):
        self.assertEqual(find([6], 6), 0)

    def test_middle(self):
        self.assertEqual(find([1, 3, 4, 6, 8, 9, 11], 6), 3)

    def test_ends(self):
        self.assertEqual(find([1, 3, 4, 6, 8, 9, 11], 1), 0)
        self.assertEqual(find([1, 3, 4, 6, 8, 9, 11], 11), 6)

    def test_large(self):
        values = list(range(0, 20000, 2))
        self.assertEqual(find(values, 15000), 7500)

    def test_missing(self):
        for values, target in (([1, 3, 5], 4), ([1, 3, 5], 0), ([1, 3, 5], 9), ([], 1)):
            with self.assertRaises(ValueError):
                find(values, target)

    def test_does_not_scan(self):
        values = Counting(range(100000))
        Counting.reads = 0
        self.assertEqual(find(values, 99998), 99998)
        self.assertLess(Counting.reads, 100)
