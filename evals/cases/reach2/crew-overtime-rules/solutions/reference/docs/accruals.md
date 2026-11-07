# Month-end wage accrual

At month end finance accrues the wages crews have earned but that haven't gone through payroll's
books yet. `python -m ledger accrue` works that out by cost centre from the approved timesheets.

## Which weeks

A month's accrual covers the pay weeks that **start** in the month, Monday to Sunday, even when the
Sunday falls in the next month. Every pay week is therefore accrued exactly once. November 2026
covers the weeks of 2, 9, 16, 23 and 30 November.

## How it's worked out

The inputs (shifts, base rates in pence, the weeks covered) are loaded into an in-memory SQLite
database and `ledger/sql/wage_accrual.sql` does all the arithmetic: quarter-hour rounding, the split
into base and premium minutes (minutes past 10 hours in a day, then the rest past 40 hours in the
worker's week), and the cost per cost centre in whole pence.
`python -m ledger show-sql` prints it. Remote-site allowances aren't accrued; finance posts them from
the pay run.

## Output

Per cost centre: hours, premium hours and the accrued amount. `--journal-out F` also writes the
finance system's journal CSV: a debit to 5100 Wages per cost centre and one credit to 2210 Accrued
wages. The reversal on the first of the next month is set up in the finance system.
