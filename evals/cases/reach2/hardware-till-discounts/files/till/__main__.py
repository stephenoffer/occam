"""python -m till: ring sales, cash up and close the day from the command line.

    python -m till --data DIR ring BASKET.json
    python -m till --data DIR cashup --date 2026-11-09 [--counted-cash 245.10] [--json]
    python -m till --data DIR close --date 2026-11-09
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from catalog.products import DEFAULT_CATALOG, load_catalog
from till import cashup, endofday
from till.journal import JournalError
from till.money import parse
from till.ring import RingError, read_basket_file, ring


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m till")
    parser.add_argument("--data", required=True, type=Path, help="the till's data directory")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    commands = parser.add_subparsers(dest="command", required=True)
    ring_cmd = commands.add_parser("ring", help="ring a sale from a basket file")
    ring_cmd.add_argument("basket", type=Path)
    cash_cmd = commands.add_parser("cashup", help="end-of-day cash-up")
    cash_cmd.add_argument("--date", required=True, type=date.fromisoformat)
    cash_cmd.add_argument("--counted-cash", type=parse, help="cash counted in the drawer, e.g. 245.10")
    cash_cmd.add_argument("--json", action="store_true")
    close_cmd = commands.add_parser("close", help="close the day")
    close_cmd.add_argument("--date", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)

    try:
        if args.command == "ring":
            rung = ring(args.data, read_basket_file(args.basket), load_catalog(args.catalog))
            sys.stdout.write(rung.receipt)
        elif args.command == "cashup":
            result = cashup.cash_up(args.data, args.date, args.counted_cash)
            if args.json:
                print(json.dumps(cashup.as_json(result), indent=2))
            else:
                sys.stdout.write(cashup.render(result))
        else:
            print(endofday.close_day(args.data, args.date))
    except (RingError, JournalError, endofday.AlreadyClosed) as exc:
        print(f"till: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
