import unittest

from school import School


class TestSchool(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(School().roster(), [])
        self.assertEqual(School().grade(1), [])

    def test_add(self):
        s = School()
        self.assertTrue(s.add("Aimee", 2))
        self.assertEqual(s.roster(), ["Aimee"])

    def test_duplicate(self):
        s = School()
        s.add("Aimee", 2)
        self.assertFalse(s.add("Aimee", 2))
        self.assertFalse(s.add("Aimee", 3))
        self.assertEqual(s.roster(), ["Aimee"])

    def test_grade_sorted(self):
        s = School()
        for name in ("Franklin", "Bradley", "Jeff"):
            s.add(name, 5)
        s.add("Zed", 4)
        self.assertEqual(s.grade(5), ["Bradley", "Franklin", "Jeff"])

    def test_roster_order(self):
        s = School()
        s.add("Chelsea", 3)
        s.add("Logan", 1)
        s.add("Anna", 3)
        self.assertEqual(s.roster(), ["Logan", "Anna", "Chelsea"])
