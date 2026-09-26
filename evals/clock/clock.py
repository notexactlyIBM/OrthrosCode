"""A clock without dates."""


class Clock:
    def __init__(self, hour, minute):
        raise NotImplementedError

    def __str__(self):
        raise NotImplementedError

    def add(self, minutes):
        raise NotImplementedError

    def subtract(self, minutes):
        raise NotImplementedError
