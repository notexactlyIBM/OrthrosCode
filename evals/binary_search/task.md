Binary search in search.py.

- [ ] In `find` (search.py), return the index of `target` in the sorted list `values`, halving the range each step rather than scanning. Done when: `find([1, 3, 4, 6, 8, 9, 11], 6)` returns 3.
- [ ] In `find` (search.py), raise `ValueError` when the target is not there, including for an empty list. Done when: `find([], 1)` raises `ValueError`.
- [ ] In `find` (search.py), work at both ends and for a list of one. Done when: `find([1, 3, 4, 6], 1)` returns 0 and `find([1, 3, 4, 6], 6)` returns 3.
