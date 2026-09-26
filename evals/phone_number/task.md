Clean up North American phone numbers in phone.py.

- [ ] In `PhoneNumber` (phone.py), keep only the digits of the text given, drop a leading country code 1 from an 11-digit number, and keep the 10 digits as `number`. Done when: `PhoneNumber("+1 (613)-995-0253").number` is `"6139950253"`.
- [ ] In `PhoneNumber` (phone.py), raise `ValueError` for letters, punctuation other than `+ ( ) - . space`, a wrong number of digits, an 11-digit number not starting with 1, and an area code or exchange code (the 1st or 4th digit) of 0 or 1. Done when: `PhoneNumber("(023) 456-7890")` raises `ValueError`.
- [ ] In `PhoneNumber.area_code` and `PhoneNumber.pretty` (phone.py), give the first three digits, and `(XXX)-XXX-XXXX`. Done when: `PhoneNumber("2234567890").pretty()` returns `"(223)-456-7890"`.
