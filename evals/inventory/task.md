Keep stock counts in inventory.py.

- [ ] In `Inventory.add` and `Inventory.count` (inventory.py), add a quantity of a named item and report how many there are; an item never added counts 0. Done when: adding 3 apples then 2 apples gives a count of 5.
- [ ] In `Inventory.remove` (inventory.py), take a quantity away; removing more than there is raises `ValueError` and changes nothing, and an item that reaches 0 is dropped. Done when: removing 6 of 5 apples raises `ValueError` and leaves 5.
- [ ] In `Inventory.add` and `Inventory.remove` (inventory.py), raise `ValueError` for a quantity that is not a positive whole number. Done when: `add("apple", 0)` raises `ValueError`.
- [ ] In `Inventory.report` (inventory.py), return a list of `(item, count)` pairs, most first and then by name. Done when: with 2 pears, 5 apples and 2 figs, `report()` returns `[("apples", 5), ("figs", 2), ("pears", 2)]`.
