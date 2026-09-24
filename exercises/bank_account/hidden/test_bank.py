import unittest

from bank import BankAccount


def opened():
    account = BankAccount()
    account.open()
    return account


class TestBankAccount(unittest.TestCase):
    def test_new_balance_is_zero(self):
        self.assertEqual(opened().balance, 0)

    def test_deposits_add(self):
        a = opened()
        a.deposit(100)
        a.deposit(50)
        self.assertEqual(a.balance, 150)

    def test_withdraw(self):
        a = opened()
        a.deposit(100)
        a.withdraw(30)
        self.assertEqual(a.balance, 70)

    def test_closed_account_refuses(self):
        a = opened()
        a.close()
        for action in (lambda: a.balance, lambda: a.deposit(1), lambda: a.withdraw(1), a.close):
            with self.assertRaises(ValueError):
                action()

    def test_never_opened_refuses(self):
        with self.assertRaises(ValueError):
            BankAccount().deposit(10)

    def test_cannot_open_twice(self):
        with self.assertRaises(ValueError):
            opened().open()

    def test_reopen_starts_at_zero(self):
        a = opened()
        a.deposit(10)
        a.close()
        a.open()
        self.assertEqual(a.balance, 0)

    def test_bad_amounts(self):
        a = opened()
        for bad in (0, -5):
            with self.assertRaises(ValueError):
                a.deposit(bad)
            with self.assertRaises(ValueError):
                a.withdraw(bad)

    def test_overdraw(self):
        a = opened()
        a.deposit(10)
        with self.assertRaises(ValueError):
            a.withdraw(11)
