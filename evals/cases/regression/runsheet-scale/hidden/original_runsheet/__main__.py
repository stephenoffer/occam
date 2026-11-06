"""Command line interface: python -m runsheet."""

import argparse
import sys
from pathlib import Path

from . import PlanError, order, parse, subset, waves


def build_parser():
    parser = argparse.ArgumentParser(prog="runsheet", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    order_command = commands.add_parser("order", help="print the run order")
    order_command.add_argument("sheet")
    waves_command = commands.add_parser("waves", help="print steps that can run in parallel")
    waves_command.add_argument("sheet")
    waves_command.add_argument("--limit", type=int, default=None)
    subset_command = commands.add_parser("subset", help="print what the targets need")
    subset_command.add_argument("sheet")
    subset_command.add_argument("targets", nargs="+")
    return parser


def read_sheet(path):
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        steps = parse(read_sheet(args.sheet))
        if args.command == "order":
            lines = order(steps)
        elif args.command == "subset":
            lines = subset(steps, args.targets)
        else:
            lines = [f"{number}: {' '.join(wave)}"
                     for number, wave in enumerate(waves(steps, args.limit), start=1)]
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
