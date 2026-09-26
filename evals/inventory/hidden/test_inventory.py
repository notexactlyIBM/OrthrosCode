import unittest

from inventory import Inventory


class TestInventory(unittest.TestCase):
    def test_add_and_count(self):
        inv = Inventory()
        inv.add("apples", 3)
        inv.add("apples", 2)
        self.assertEqual(inv.count("apples"), 5)

    def test_unknown_is_zero(self):
        self.assertEqual(Inventory().count("kiwis"), 0)

    def test_remove(self):
        inv = Inventory()
        inv.add("apples", 5)
        inv.remove("apples", 2)
        self.assertEqual(inv.count("apples"), 3)

    def test_remove_too_many(self):
        inv = Inventory()
        inv.add("apples", 5)
        with self.assertRaises(ValueError):
            inv.remove("apples", 6)
        self.assertEqual(inv.count("apples"), 5)
        with self.assertRaises(ValueError):
            inv.remove("kiwis", 1)

    def test_zero_is_dropped(self):
        inv = Inventory()
        inv.add("apples", 2)
        inv.remove("apples", 2)
        self.assertEqual(inv.report(), [])

    def test_bad_quantities(self):
        inv = Inventory()
        for q in (0, -1, 1.5, "2"):
            with self.assertRaises(ValueError):
                inv.add("apples", q)
        inv.add("apples", 1)
        with self.assertRaises(ValueError):
            inv.remove("apples", 0)

    def test_report_order(self):
        inv = Inventory()
        inv.add("pears", 2)
        inv.add("apples", 5)
        inv.add("figs", 2)
        self.assertEqual(inv.report(), [("apples", 5), ("figs", 2), ("pears", 2)])
