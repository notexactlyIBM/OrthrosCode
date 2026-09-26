import unittest

from matrix import Matrix


class TestMatrix(unittest.TestCase):
    def test_single(self):
        self.assertEqual(Matrix("1").row(1), [1])
        self.assertEqual(Matrix("1").column(1), [1])

    def test_row(self):
        self.assertEqual(Matrix("1 2\n10 20").row(2), [10, 20])

    def test_column(self):
        self.assertEqual(Matrix("1 2 3\n4 5 6\n7 8 9").column(3), [3, 6, 9])

    def test_non_square(self):
        m = Matrix("1 2 3\n4 5 6")
        self.assertEqual(m.row(1), [1, 2, 3])
        self.assertEqual(m.column(2), [2, 5])

    def test_transpose(self):
        t = Matrix("1 2 3\n4 5 6").transpose()
        self.assertEqual(t.row(1), [1, 4])
        self.assertEqual(t.row(3), [3, 6])
        self.assertEqual(t.column(2), [4, 5, 6])

    def test_out_of_range(self):
        m = Matrix("1 2\n3 4")
        for bad in (lambda: m.row(0), lambda: m.row(3), lambda: m.column(0),
                    lambda: m.column(3)):
            with self.assertRaises(IndexError):
                bad()

    def test_rows_are_copies(self):
        m = Matrix("1 2\n3 4")
        m.row(1).append(99)
        self.assertEqual(m.row(1), [1, 2])
