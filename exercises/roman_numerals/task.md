Build `to_roman` and `from_roman` in roman.py for the numbers 1 to 3999.

- [ ] In `to_roman` (roman.py), turn an int from 1 to 3999 into Roman numerals, using the subtractive forms (IV, IX, XL, XC, CD, CM). Done when: `to_roman(1994)` is "MCMXCIV" and `to_roman(3999)` is "MMMCMXCIX".
- [ ] In `to_roman` (roman.py), raise `ValueError` for 0, negatives, numbers over 3999 and anything that is not an int. Done when: `to_roman(0)` and `to_roman(4000)` raise `ValueError`.
- [ ] In `from_roman` (roman.py), turn a numeral back into an int, accepting lower case. Done when: `from_roman("mcmxciv")` is 1994.
- [ ] In `from_roman` (roman.py), raise `ValueError` for anything that is not a well-formed numeral: unknown letters, "IIII", "IM", empty text. Done when: those raise `ValueError` and every number from 1 to 3999 survives `from_roman(to_roman(n)) == n`.
