Build a `BankAccount` class in bank.py that holds a balance and refuses anything that makes no sense.

- [ ] In `BankAccount` (bank.py), add `open()`, `close()` and a `balance` property; a new account is closed, opening sets the balance to 0. Done when: an opened account's `balance` is 0.
- [ ] In `BankAccount.deposit` (bank.py), add money to an open account. Done when: depositing 100 then 50 gives a balance of 150.
- [ ] In `BankAccount.withdraw` (bank.py), take money out of an open account. Done when: 100 in, 30 out leaves 70.
- [ ] In bank.py, raise `ValueError` for: using a closed account (balance, deposit, withdraw, closing twice), opening an open one, amounts of 0 or less, and withdrawing more than the balance. Done when: each of those raises `ValueError`.
