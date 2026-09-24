Build `count_words` in words.py: it takes a string and returns a dict of word -> count.

- [ ] In `count_words` (words.py), split the text into words and count them. Done when: `count_words("one fish two fish")` returns `{"one": 1, "fish": 2, "two": 1}`.
- [ ] In `count_words` (words.py), ignore case, so "Go" and "go" are the same word, and return the words in lower case. Done when: `count_words("Go go GO")` returns `{"go": 3}`.
- [ ] In `count_words` (words.py), treat any punctuation other than an apostrophe inside a word as a separator, and drop apostrophes that quote a word. Done when: `count_words("'Hello,' she said. Don't!")` returns `{"hello": 1, "she": 1, "said": 1, "don't": 1}`.
- [ ] In `count_words` (words.py), count numbers as words and return an empty dict for empty or blank text. Done when: `count_words("1 2 2")` returns `{"1": 1, "2": 2}` and `count_words("  ")` returns `{}`.
