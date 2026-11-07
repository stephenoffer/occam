# Weekly pay

The pay run takes one pay week (Monday to Sunday, named by its Monday) of timesheets and produces
a payslip per worker.

## Hours

1. Only **approved** shifts are paid. A worker with submitted or draft shifts gets a note on the
   payslip and those shifts wait for next week's run once approved.
2. Each shift's worked time is end minus start minus the unpaid break, rounded to the nearest
   quarter hour.
3. **Overtime** follows the site agreement (from the pay week of 2 November 2026):
   - hours worked beyond 10 in a single day are overtime;
   - hours worked beyond 40 in the pay week are overtime, counting only the hours that weren't
     already overtime under the daily rule, so no hour is paid twice.

   Everything else is regular time. Three 12-hour days make 6 hours of overtime; four 12-hour days
   and a 4-hour Friday make 12 (8 daily, then 44 - 40 weekly).

## Pay

- Basic pay is regular hours times the worker's base rate.
- Overtime pay is overtime hours times the base rate times the overtime multiplier, 1.5.
- Remote-site allowances are a flat amount per approved shift at sites listed with one in
  `data/sites.csv`.
- Basic and overtime pay are each rounded to the penny, half up, as the bureau's import expects.

## Running

```sh
python -m payroll run --timesheets F --rates data/rates.csv --week 2026-10-26 --sites data/sites.csv --json
```

Validation problems (overlapping shifts, a shift that ends before it starts, a worker with no rate)
stop the run. `--ignore-problems` pays what it can and is only for re-runs payroll has checked by hand.

## After the run

`python -m exports bureau` turns the JSON into the bureau's import file. See [bureau.md](bureau.md).
