"""A school roster."""


class School:
    def add(self, name, grade):
        raise NotImplementedError

    def grade(self, number):
        raise NotImplementedError

    def roster(self):
        raise NotImplementedError
