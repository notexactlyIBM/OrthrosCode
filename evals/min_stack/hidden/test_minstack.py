import unittest

from minstack import MinStack


class TestMinStack(unittest.TestCase):
    def test_push_pop(self):
        s = MinStack()
        s.push(1)
        s.push(2)
        self.assertEqual(s.pop(), 2)
        self.assertEqual(s.pop(), 1)

    def test_peek_does_not_remove(self):
        s = MinStack()
        s.push(4)
        self.assertEqual(s.peek(), 4)
        self.assertEqual(len(s), 1)

    def test_min(self):
        s = MinStack()
        for x in (5, 3, 7):
            s.push(x)
        self.assertEqual(s.min(), 3)

    def test_min_after_pops(self):
        s = MinStack()
        for x in (5, 3, 7, 1):
            s.push(x)
        s.pop()
        self.assertEqual(s.min(), 3)
        s.pop()
        s.pop()
        self.assertEqual(s.min(), 5)

    def test_duplicate_minimums(self):
        s = MinStack()
        for x in (2, 1, 1):
            s.push(x)
        s.pop()
        self.assertEqual(s.min(), 1)

    def test_len(self):
        s = MinStack()
        self.assertEqual(len(s), 0)
        s.push(9)
        s.push(8)
        self.assertEqual(len(s), 2)

    def test_empty_raises(self):
        for action in ("pop", "peek", "min"):
            with self.assertRaises(IndexError):
                getattr(MinStack(), action)()
