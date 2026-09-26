Check numbers with the Luhn formula, in luhn.py.

- [ ] In `valid` (luhn.py), double every second digit from the right (subtracting 9 when the result is over 9), sum all digits, and accept when the sum is divisible by 10. Done when: `valid("4539 3195 0343 6467")` returns True and `valid("8273 1232 7352 0569")` returns False.
- [ ] In `valid` (luhn.py), ignore spaces, and reject any other non-digit and any number of fewer than two digits. Done when: `valid("0")` returns False and `valid("055a 444 285")` returns False.
