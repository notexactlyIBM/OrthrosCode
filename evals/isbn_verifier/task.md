Check ISBN-10 numbers in isbn.py.

- [ ] In `is_valid` (isbn.py), accept a 10-character ISBN of digits whose weighted sum (first digit times 10, second times 9, ... last times 1) is divisible by 11. Done when: `is_valid("3598215088")` returns True and `is_valid("3598215089")` returns False.
- [ ] In `is_valid` (isbn.py), allow `X` as the last character only, worth 10, and ignore dashes. Done when: `is_valid("3-598-21507-X")` returns True and `is_valid("3-598-2X507-9")` returns False.
- [ ] In `is_valid` (isbn.py), return False for anything of the wrong length or with other characters. Done when: `is_valid("3598215078X")`, `is_valid("")` and `is_valid("359821507A")` all return False.
