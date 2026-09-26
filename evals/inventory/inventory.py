"""Stock counts."""


class Inventory:
    def add(self, item, quantity):
        raise NotImplementedError

    def remove(self, item, quantity):
        raise NotImplementedError

    def count(self, item):
        raise NotImplementedError

    def report(self):
        raise NotImplementedError
