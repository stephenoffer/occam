# crewworks

Back-office tools for Halyard Field Services' site crews: reading timesheets, paying the week,
pricing planned rosters for site budgets and bids, and the month-end wage accrual.

Everything is plain Python 3.10+ with no third-party dependencies. Money and hours are `Decimal`
(see [ADR 0001](docs/adr/0001-decimal-hours.md)).

## Packages

| Package | What it does |
|---|---|
| `timesheets` | Reads the weekly timesheet export from the site app, rounds each shift to the quarter hour and checks it before pay. |
| `payroll` | The weekly pay run: regular hours, overtime, remote-site allowances and payslips. See [docs/payroll.md](docs/payroll.md). |
| `exports` | The fixed-width file the payroll bureau imports, built from the pay run's JSON. See [docs/bureau.md](docs/bureau.md). |
| `rostering` | Shift patterns site managers plan from, and warnings for rest, shift length and long weeks. |
| `costing` | What a planned roster will cost each site, premium time and employer on-costs included. Estimating uses it for bids, site managers for budgets. See [docs/costing.md](docs/costing.md). |
| `ledger` | The month-end wage accrual finance posts, by cost centre. The figures are worked out in SQL so they can be audited ([ADR 0002](docs/adr/0002-accruals-in-sql.md), [docs/accruals.md](docs/accruals.md)). |
| `common` | Pay weeks, money and CSV helpers. |

## Running

```sh
python -m payroll run --timesheets data/timesheets/2026-10-26.csv --rates data/rates.csv --week 2026-10-26
python -m payroll run ... --json > payslips.json
python -m exports bureau --payslips payslips.json --out PAYIMP.txt

python -m rostering expand --pattern long-days --worker W106 --site MLT --from 2026-11-02 --weeks 4 --out plan.csv
python -m rostering check plan.csv
python -m costing forecast --roster data/roster/plan-2026-11.csv --rates data/rates.csv --sites data/sites.csv

python -m ledger accrue --timesheets data/timesheets/2026-10-26.csv --rates data/rates.csv --month 2026-10
python -m ledger show-sql
```

Every command takes `--json` where another tool or a spreadsheet reads the output.

## Data

`data/` holds sample inputs: `rates.csv` (base hourly rate per worker), `sites.csv` (site names,
cost centres and remote allowances), a week of timesheets and a month's planned roster. Real
inputs live on the finance share and never go in the repository.

## Tests

```sh
python -m pytest
scripts/check.sh      # tests plus a byte-compile of every module
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and
[docs/glossary.md](docs/glossary.md) for the terms the crews, payroll and finance use.
