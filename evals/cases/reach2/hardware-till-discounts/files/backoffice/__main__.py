"""python -m backoffice: head office's daily takings.

    python -m backoffice takings --inbox DIR --date 2026-11-09 [--json]
    python -m backoffice postings --inbox DIR --date 2026-11-09 > postings.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from backoffice import nominal
from backoffice.takings import as_json, takings_for_day


def pounds(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    return f"{sign}{abs(pence) // 100}.{abs(pence) % 100:02d}"


def print_takings(data: dict) -> None:
    for store, t in data["stores"].items():
        print(f"{store}: {t['sales_count']} sales, {pounds(t['sales_pence'])}")
        for dept, pence in t["departments"].items():
            print(f"  {dept:<6}{pounds(pence):>12}")
        print(f"  banked cash {pounds(t['banked_cash_pence'])}, card {pounds(t['tenders'].get('card', 0))}")
        for sale in t["mismatches"]:
            print(f"  CHECK sale {sale}: lines don't match payment")
        for q in t["quarantined"]:
            print(f"  QUARANTINED {q['tape']} line {q['line']}: {q['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backoffice")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("takings", "postings"):
        command = commands.add_parser(name)
        command.add_argument("--inbox", required=True, type=Path)
        command.add_argument("--date", required=True, type=date.fromisoformat)
        if name == "takings":
            command.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    takings = takings_for_day(args.inbox, args.date)
    if args.command == "postings":
        sys.stdout.write(nominal.to_csv([takings[store] for store in sorted(takings)]))
    elif args.json:
        print(json.dumps(as_json(takings), indent=2))
    else:
        print_takings(as_json(takings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
