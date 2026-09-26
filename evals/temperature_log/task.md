Summarise a temperature log in readings.py. Each line is `HH:MM value`, like `07:30 18.5`.

- [ ] In `parse` (readings.py), turn the log's text into a list of `(minutes since midnight, value)` pairs, skipping blank lines and lines that are not a valid time and number. Done when: `parse("07:30 18.5\nnonsense\n25:00 3")` returns `[(450, 18.5)]`.
- [ ] In `stats` (readings.py), return a dict with `min`, `max`, `mean` and `median` of the values in the text, the mean rounded to 2 places. Done when: for values 10, 20 and 40, `stats` gives min 10, max 40, mean 23.33 and median 20.
- [ ] In `stats` (readings.py), raise `ValueError` when the text has no valid readings. Done when: `stats("bad\n")` raises `ValueError`.
