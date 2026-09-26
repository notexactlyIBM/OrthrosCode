"""North American phone numbers."""


class PhoneNumber:
    def __init__(self, text):
        raise NotImplementedError

    @property
    def area_code(self):
        raise NotImplementedError

    def pretty(self):
        raise NotImplementedError
