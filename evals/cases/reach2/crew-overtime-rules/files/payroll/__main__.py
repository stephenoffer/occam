"""Weekly pay run.

    python -m payroll run --timesheets data/timesheets/2026-10-26.csv --rates data/rates.csv --week 2026-10-26 [--json]

Prints one line per worker, or JSON with --json (exports/bureau.py reads that JSON).
Problems found by timesheets.validate stop the run unless --ignore-problems is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from common.csvio import CsvError
from common.money import fmt, plain
from common.weeks import WeekError, parse_week, week_start
from payroll.allowances import allowance_for, load_site_allowances
from payroll.hours import split_all
from payroll.payslip import build_payslip
from payroll.rates import load_rates
from timesheets.parse import load_timesheets
from timesheets.validate import problems


def run(args: argparse.Namespace) -> int:
    try:
        week = parse_week(args.week)
        shifts = load_timesheets(args.timesheets)
        rates = load_rates(args.rates)
        allowances = load_site_allowances(args.sites) if args.sites else {}
    except (CsvError, WeekError, OSError) as exc:
        print(f"payroll: {exc}", file=sys.stderr)
        return 2
    in_week = [s for s in shifts if week_start(s.work_date) == week]
    found = problems(in_week, known_workers=set(rates))
    if found and not args.ignore_problems:
        for problem in found:
            print(f"payroll: {problem}", file=sys.stderr)
        return 1
    drafts = sorted({s.worker_id for s in in_week if not s.approved})
    payslips = []
    for worker, hours in split_all(in_week, week).items():
        if worker not in rates:
            continue
        slip = build_payslip(hours, rates[worker], allowance_for(worker, in_week, allowances))
        if worker in drafts:
            slip.notes.append("has unapproved shifts this week, not paid")
        payslips.append(slip)
    total = sum((slip.gross for slip in payslips), Decimal(0))
    if args.json:
        print(json.dumps({"week": week.isoformat(), "payslips": [slip.as_dict() for slip in payslips],
                          "total_gross": plain(total)}, indent=2))
    else:
        for slip in payslips:
            print(f"{slip.worker_id:<6} {slip.name:<22} reg {slip.regular_hours:>6.2f}  ot {slip.overtime_hours:>6.2f}"
                  f"  gross {fmt(slip.gross):>10}")
        print(f"{len(payslips)} payslips, total gross {fmt(total)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m payroll")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="pay one week")
    run_parser.add_argument("--timesheets", required=True)
    run_parser.add_argument("--rates", required=True)
    run_parser.add_argument("--week", required=True, help="the Monday of the pay week, YYYY-MM-DD")
    run_parser.add_argument("--sites", help="sites CSV with remote allowances")
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument("--ignore-problems", action="store_true")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
