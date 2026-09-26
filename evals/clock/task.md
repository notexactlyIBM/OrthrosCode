A clock without dates, in clock.py.

- [ ] In `Clock` (clock.py), store hours and minutes and show them as `HH:MM` from `str()`, rolling over past midnight either way. Done when: `str(Clock(25, 160))` returns `"03:40"` and `str(Clock(-1, 15))` returns `"23:15"`.
- [ ] In `Clock.add` and `Clock.subtract` (clock.py), return a new clock that many minutes later or earlier. Done when: `str(Clock(23, 59).add(2))` returns `"00:01"`.
- [ ] In `Clock` (clock.py), make two clocks showing the same time equal. Done when: `Clock(0, 1440) == Clock(0, 0)` is True.
