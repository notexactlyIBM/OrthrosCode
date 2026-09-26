import time
import unittest

from perfect import classify


class TestClassify(unittest.TestCase):
    def test_perfect(self):
        for n in (6, 28, 496):
            self.assertEqual(classify(n), "perfect")

    def test_abundant(self):
        for n in (12, 30, 33550335):
            self.assertEqual(classify(n), "abundant")

    def test_deficient(self):
        for n in (1, 2, 4, 8, 33550337):
            self.assertEqual(classify(n), "deficient")

    def test_large_is_quick(self):
        started = time.time()
        self.assertEqual(classify(33550336), "perfect")
        self.assertLess(time.time() - started, 2)

    def test_not_positive(self):
        for n in (0, -1):
            with self.assertRaises(ValueError):
                classify(n)
