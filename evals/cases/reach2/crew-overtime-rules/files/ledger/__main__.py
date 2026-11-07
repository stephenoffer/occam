"""Month-end wage accrual.

    python -m ledger accrue --timesheets F --rates F --month 2026-11 [--json] [--journal-out F]
    python -m ledger show-sql      # the query, for auditors

Only approved shifts are accrued. See docs/accruals.md for which pay weeks a month covers.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from common.csvio import CsvError
from common.money import fmt, plain
from common.weeks import WeekError
from ledger.journal import write_journal
from ledger.load import load_rates, load_shifts, load_weeks, open_db, pounds, sql_text
from ledger.periods import weeks_for_month
from timesheets.parse import load_timesheets

QUERY = "wage_accrual.sql"


def accrue(args: argparse.Namespace) -> int:
    try:
        weeks = weeks_for_month(args.month)
        shifts = load_timesheets(args.timesheets)
        conn = open_db()
        load_shifts(conn, shifts)
        load_rates(conn, args.rates)
        load_weeks(conn, weeks)
    except (CsvError, WeekError, OSError) as exc:
        print(f"ledger: {exc}", file=sys.stderr)
        return 2
    unrated = [row[0] for row in conn.execute(
        "SELECT DISTINCT s.worker_id FROM shifts s LEFT JOIN rates r USING (worker_id) "
        "WHERE r.worker_id IS NULL AND s.status = 'approved' ORDER BY 1")]
    if unrated:
        print(f"ledger: no base rate for {', '.join(unrated)}", file=sys.stderr)
        return 2
    rows = conn.execute(sql_text(QUERY)).fetchall()
    centres = [{
        "cost_centre": centre,
        "hours": f"{Decimal(minutes) / 60:.2f}",
        "premium_hours": f"{Decimal(premium) / 60:.2f}",
        "accrued": plain(pounds(accrued)),
    } for centre, minutes, premium, accrued in rows]
    accrued_by_centre = {row["cost_centre"]: Decimal(row["accrued"]) for row in centres}
    total = sum(accrued_by_centre.values(), Decimal(0))
    if args.journal_out:
        write_journal(args.journal_out, args.month, accrued_by_centre)
    if args.json:
        print(json.dumps({"month": args.month, "weeks": [w.isoformat() for w in weeks], "cost_centres": centres,
                          "total": plain(total)}, indent=2))
        return 0
    print(f"Wage accrual for {args.month} (pay weeks {weeks[0]} to {weeks[-1]})")
    for row in centres:
        print(f"  {row['cost_centre']:<10} {row['hours']:>9} h  premium {row['premium_hours']:>8} h"
              f"  {fmt(Decimal(row['accrued'])):>12}")
    print(f"  {'total':<10} {'':>9}    {'':>8}    {fmt(total):>12}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("accrue", help="accrue a month's wages by cost centre")
    cmd.add_argument("--timesheets", required=True)
    cmd.add_argument("--rates", required=True)
    cmd.add_argument("--month", required=True, help="YYYY-MM")
    cmd.add_argument("--journal-out", help="also write the finance journal CSV here")
    cmd.add_argument("--json", action="store_true")
    sub.add_parser("show-sql", help="print the accrual query")
    args = parser.parse_args(argv)
    if args.command == "show-sql":
        print(sql_text(QUERY))
        return 0
    return accrue(args)


if __name__ == "__main__":
    sys.exit(main())
