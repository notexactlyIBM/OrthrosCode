Run-length encoding in rle.py: runs of the same character become a count and the character.

- [ ] In `encode` (rle.py), turn each run of two or more equal characters into its length followed by the character; single characters stay as they are. Done when: `encode("WWWWBBBW")` returns `"4W3BW"`.
- [ ] In `decode` (rle.py), undo `encode`, including counts of more than one digit. Done when: `decode("12WB3C")` returns `"WWWWWWWWWWWWBCCC"`.
- [ ] In rle.py, handle the empty string and spaces as ordinary characters. Done when: `encode("")` returns `""` and `decode(encode("  hello  "))` gives back `"  hello  "`.
