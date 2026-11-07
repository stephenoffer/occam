# Site cost forecasts

`python -m costing forecast` prices a planned roster so estimating can bid and site managers can
set monthly budgets. It reads the roster (planned shifts, as `python -m rostering expand` writes
them) and the base rates, and reports by site:

| Column | Meaning |
|---|---|
| hours | planned paid hours |
| premium_hours | the part of those hours priced as premium time |
| wages | base hours at base rate plus premium hours at the premium factor (1.5) times base |
| oncosts | employer NI, pension, apprenticeship levy and holiday accrual, as a share of wages |
| total | wages plus on-costs |

## Premium time

Each worker's planned week is walked in date and start order. The first 40 hours are base time and
every hour after is premium. Premium hours are charged to the site whose shift they fall in, so the
site that books someone at the end of a long week carries the premium.

Vacant shifts (`worker_id` of `VACANT`) are priced at the vacant rate, 21.50 by default, with no
premium, because nobody's week is known until the shift is filled.

## On-costs

The rates are in `costing/oncosts.py` and change each April when finance publishes them. Bids priced
inclusive of holiday pass `--no-holiday`.

## Caveats

Forecasts use planned hours without quarter-hour rounding and ignore approval, allowances and
sickness. They are for budgets, not for paying anyone.
