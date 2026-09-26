Classify numbers by their divisors, in perfect.py.

- [ ] In `classify` (perfect.py), return "perfect", "abundant" or "deficient" as the sum of a positive whole number's proper divisors (all divisors but itself) equals, exceeds or falls short of it. Done when: `classify(6)` returns "perfect", `classify(12)` "abundant" and `classify(8)` "deficient".
- [ ] In `classify` (perfect.py), raise `ValueError` for 0 and negative numbers, and be quick for large numbers by only trying divisors up to the square root. Done when: `classify(33550336)` returns "perfect" in well under a second.
