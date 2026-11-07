"""Forecast what a planned roster will cost each site.

    python -m costing forecast --roster data/roster/plan-2026-11.csv --rates data/rates.csv [--sites data/sites.csv] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from common.csvio import CsvError
from common.money import fmt, pennies, plain
from costing.forecast import DEFAULT_VACANT_RATE, by_site, price
from costing.inputs import load_base_rates, load_roster
from costing.oncosts import oncost_rate
from costing.sites import label, load_site_names


def forecast(args: argparse.Namespace) -> int:
    try:
        planned = load_roster(args.roster)
        rates = load_base_rates(args.rates)
        names = load_site_names(args.sites)
        priced = price(planned, rates, Decimal(args.vacant_rate))
    except (CsvError, KeyError, OSError) as exc:
        print(f"costing: {exc}", file=sys.stderr)
        return 2
    rate = oncost_rate(exclude=("holiday_accrual",) if args.no_holiday else ())
    rows = []
    for site in by_site(priced).values():
        oncosts = pennies(site.wages * rate)
        rows.append({
            "site": site.site,
            "name": label(site.site, names),
            "weeks": [week.isoformat() for week in sorted(site.weeks)],
            "shifts": site.shifts,
            "hours": f"{site.hours:.2f}",
            "premium_hours": f"{site.premium_hours:.2f}",
            "wages": plain(site.wages),
            "oncosts": plain(oncosts),
            "total": plain(site.wages + oncosts),
        })
    grand = sum((Decimal(row["total"]) for row in rows), Decimal(0))
    if args.json:
        print(json.dumps({"oncost_rate": str(rate), "sites": rows, "total": plain(grand)}, indent=2))
        return 0
    print(f"{'site':<28} {'hours':>8} {'premium':>8} {'wages':>12} {'on-costs':>10} {'total':>12}")
    for row in rows:
        print(f"{row['name']:<28} {row['hours']:>8} {row['premium_hours']:>8} {fmt(Decimal(row['wages'])):>12}"
              f" {fmt(Decimal(row['oncosts'])):>10} {fmt(Decimal(row['total'])):>12}")
    print(f"{'total':<28} {'':>8} {'':>8} {'':>12} {'':>10} {fmt(grand):>12}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m costing")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("forecast", help="price a planned roster by site")
    cmd.add_argument("--roster", required=True)
    cmd.add_argument("--rates", required=True)
    cmd.add_argument("--sites")
    cmd.add_argument("--vacant-rate", default=str(DEFAULT_VACANT_RATE))
    cmd.add_argument("--no-holiday", action="store_true", help="leave holiday accrual out of on-costs")
    cmd.add_argument("--json", action="store_true")
    return forecast(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
