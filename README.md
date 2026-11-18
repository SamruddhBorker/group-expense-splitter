# group-expense-splitter

[![tests](https://github.com/SamruddhBorker/group-expense-splitter/actions/workflows/tests.yml/badge.svg)](https://github.com/SamruddhBorker/group-expense-splitter/actions/workflows/tests.yml)

Split trip and shared costs fairly, track who owes whom, and settle up with the
fewest payments. Built for friend trips, flatmates and college projects.

**The problem:** after a trip, someone is stuck doing the maths on a phone
calculator, the totals never quite add up, and everyone argues about who owes what.

- Python 3.9+, **standard library only**, data in a single `trip.json`
- **Exact to the paisa**: money is stored as integers, and shares always add up to the total
- Optional UPI pay links for the payments you need to make

## Quick start

```bash
python split.py new "Goa Trip" --members Asha Ben Chitra
python split.py add --paid-by Asha --amount 3600 --desc "Dinner"                      # equal split
python split.py add --paid-by Ben --amount 900 --desc "Cab" --among Ben Chitra       # only some people
python split.py add --paid-by Asha --amount 5000 --desc "Villa" --mode percent --values 50 30 20
python split.py add --paid-by Ben --amount 1200 --desc "Food" --mode shares --values 2 1 1
python split.py balances        # who is owed / who owes
python split.py settle          # the payments that clear everything
python split.py paid Chitra Asha 500
python split.py upi Asha asha@okbank     # then `settle` prints a UPI pay link
python split.py list | undo | summary | export trip.csv
```

## Split modes

| Mode | Meaning |
|---|---|
| `equal` (default) | same share for everyone listed |
| `exact` | you give each person's amount; they must add up to the total |
| `percent` | percentages that must add up to 100 |
| `shares` | weights, like 2:1:1 for "I had two portions" |

The payer doesn't have to be in the split ("I bought a gift for Ben").
If 100 can't divide by 3, the extra paisa goes to the first person, so
33.34 + 33.33 + 33.33 = 100.00 exactly.

## How settle works

The biggest debtor pays the biggest creditor, repeatedly. That never needs more
than *members − 1* payments. It isn't always the theoretical minimum (that problem
is NP-hard), but it is simple and easy to follow. The tests check on hundreds of
random trips that following the suggestions brings every balance to exactly zero.

## Honest limits

- The UPI link uses the standard `upi://pay` format. It hasn't been tested against
  every UPI app, so check the amount before approving
- One currency (₹), no live sync between phones: share the `trip.json` file or the CSV
- Names must be unique within a group

## Safety

- Writes are atomic (temp file then replace), so a crash can't corrupt your trip
- CSV export neutralises spreadsheet formulas; `new` won't overwrite an existing trip without `--force`

## Tests

```bash
python -m unittest -v
```

## License

MIT
