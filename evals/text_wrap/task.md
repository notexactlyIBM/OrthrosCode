Wrap text to a width in wrap.py.

- [ ] In `wrap` (wrap.py), split text into lines of at most `width` characters, breaking only between words and putting as many words on each line as fit. Done when: `wrap("the quick brown fox", 10)` returns `["the quick", "brown fox"]`.
- [ ] In `wrap` (wrap.py), treat any run of spaces, tabs or newlines as one break between words, and return `[]` for text with no words. Done when: `wrap("  a\n\tb  ", 10)` returns `["a b"]`.
- [ ] In `wrap` (wrap.py), put a word longer than the width on a line of its own, unbroken, and raise `ValueError` for a width under 1. Done when: `wrap("a extraordinary b", 5)` returns `["a", "extraordinary", "b"]`.
