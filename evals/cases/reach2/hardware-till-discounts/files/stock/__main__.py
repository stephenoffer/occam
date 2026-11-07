"""python -m stock --data DIR deplete --date D | show"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock.deplete import deplete_day
from stock.levels import load_levels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stock")
    parser.add_argument("--data", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    deplete = commands.add_parser("deplete")
    deplete.add_argument("--date", required=True, type=date.fromisoformat)
    commands.add_parser("show")
    args = parser.parse_args(argv)
    if args.command == "deplete":
        for sku in deplete_day(args.data, args.date):
            print(f"below zero: {sku}")
    else:
        for sku, on_hand in sorted(load_levels(args.data).items()):
            print(f"{sku:<16}{on_hand:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
