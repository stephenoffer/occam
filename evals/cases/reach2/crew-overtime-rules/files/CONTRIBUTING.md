# Contributing

## Ground rules

- Money and hours are `Decimal`, never `float`, in Python. SQL keeps money in whole pence and time
  in whole minutes (ADR 0001, ADR 0002).
- Round once, at the edge: pennies when a figure is reported or paid, quarter hours per shift.
- CLIs print JSON with `--json`. Other tools and spreadsheets read those keys, so don't rename or
  remove one without telling the people who use it (the bureau export reads payroll's JSON).
- New behaviour comes with tests in `tests/`, named after the package (`test_payroll_*.py`,
  `test_ledger_*.py` and so on). Test files must have unique names; there are no `__init__.py`
  files in `tests/`.
- Dates are ISO (`2026-11-02`); pay weeks are named by their Monday.

## Checks

`scripts/check.sh` runs the tests and byte-compiles everything. It must pass before review.

## Reviews

Changes to anything that decides how much someone is paid need a second reviewer from payroll.
Changes to the accrual query need finance to sign off, because the auditors re-run it.

## Releases

Version is in `pyproject.toml`. We tag `vX.Y.Z` and the payroll office pulls the tag on Monday
morning before the pay run.
