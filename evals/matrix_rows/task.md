Read a matrix from text in matrix.py: rows are lines, numbers are separated by spaces.

- [ ] In `Matrix.row` (matrix.py), return row `i` as a list of ints, counting from 1. Done when: `Matrix("1 2\n3 4").row(2)` returns `[3, 4]`.
- [ ] In `Matrix.column` (matrix.py), return column `i` as a list of ints, counting from 1. Done when: `Matrix("1 2 3\n4 5 6").column(3)` returns `[3, 6]`.
- [ ] In `Matrix.transpose` (matrix.py), return a new `Matrix` whose rows are the old columns. Done when: `Matrix("1 2\n3 4").transpose().row(1)` returns `[1, 3]`.
- [ ] In `Matrix` (matrix.py), raise `IndexError` for a row or column number that is out of range, including 0. Done when: `Matrix("1 2").row(0)` raises `IndexError`.
