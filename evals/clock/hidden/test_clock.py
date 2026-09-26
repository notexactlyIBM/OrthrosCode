import unittest

from clock import Clock


class TestClock(unittest.TestCase):
    def test_on_the_hour(self):
        self.assertEqual(str(Clock(8, 0)), "08:00")

    def test_rolls_over(self):
        self.assertEqual(str(Clock(25, 160)), "03:40")
        self.assertEqual(str(Clock(72, 8640)), "00:00")

    def test_negative(self):
        self.assertEqual(str(Clock(-1, 15)), "23:15")
        self.assertEqual(str(Clock(1, -40)), "00:20")
        self.assertEqual(str(Clock(-25, -160)), "20:20")

    def test_add(self):
        self.assertEqual(str(Clock(10, 0).add(3)), "10:03")
        self.assertEqual(str(Clock(23, 59).add(2)), "00:01")

    def test_subtract(self):
        self.assertEqual(str(Clock(0, 3).subtract(4)), "23:59")
        self.assertEqual(str(Clock(5, 32).subtract(1500)), "04:32")

    def test_add_returns_new_clock(self):
        c = Clock(1, 0)
        c.add(30)
        self.assertEqual(str(c), "01:00")

    def test_equal(self):
        self.assertEqual(Clock(0, 1440), Clock(0, 0))
        self.assertEqual(Clock(-2, -60), Clock(21, 0))
        self.assertNotEqual(Clock(1, 0), Clock(0, 1))
