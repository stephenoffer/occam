"""Build and check planned rosters.

    python -m rostering expand --pattern long-days --worker W104 --site HBR --from 2026-11-02 --weeks 4 --out plan.csv
    python -m rostering check plan.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from common.csvio import read_rows
from rostering.checks import warnings
from rostering.roster import FIELDS, append_rows, expand


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rostering")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("expand", help="add a worker's pattern to a roster file")
    exp.add_argument("--pattern", required=True)
    exp.add_argument("--worker", default="VACANT")
    exp.add_argument("--site", required=True)
    exp.add_argument("--from", dest="first", required=True)
    exp.add_argument("--weeks", type=int, default=4)
    exp.add_argument("--out", required=True)
    chk = sub.add_parser("check", help="warn about rest, shift length and long weeks")
    chk.add_argument("roster")
    args = parser.parse_args(argv)
    if args.command == "expand":
        try:
            rows = expand(args.pattern, args.worker, args.site, date.fromisoformat(args.first), args.weeks)
        except (KeyError, ValueError) as exc:
            print(f"rostering: {exc}", file=sys.stderr)
            return 2
        total = append_rows(args.out, rows)
        print(f"added {len(rows)} shifts, {total} in {args.out}")
        return 0
    found = warnings(read_rows(args.roster, FIELDS))
    for warning in found:
        print(warning)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
