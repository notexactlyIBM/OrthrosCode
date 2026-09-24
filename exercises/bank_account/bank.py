"""A bank account that refuses what makes no sense."""


class BankAccount:
    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    @property
    def balance(self):
        raise NotImplementedError

    def deposit(self, amount):
        raise NotImplementedError

    def withdraw(self, amount):
        raise NotImplementedError
