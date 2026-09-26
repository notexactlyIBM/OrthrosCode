"""A matrix read from text."""


class Matrix:
    def __init__(self, text):
        raise NotImplementedError

    def row(self, i):
        raise NotImplementedError

    def column(self, i):
        raise NotImplementedError

    def transpose(self):
        raise NotImplementedError
