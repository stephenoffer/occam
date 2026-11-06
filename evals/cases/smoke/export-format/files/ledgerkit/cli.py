import argparse
import sys

from . import batch, config
from .formats import REGISTRY
from .ledger import filter_rows, load_ledger
from .money import round_display_amount
from .text import to_url_token


def build_parser():
    parser = argparse.ArgumentParser(prog="ledgerkit")
    parser.add_argument("--list-formats", action="store_true")
    commands = parser.add_subparsers(dest="command")

    export = commands.add_parser("export")
    export.add_argument("input")
    export.add_argument("--format", choices=config.ALLOWED_FORMATS, default=config.DEFAULT_FORMAT)
    export.add_argument("--currency")
    export.add_argument("--summary-row", action="store_true")

    summary = commands.add_parser("summary")
    summary.add_argument("input")

    job = commands.add_parser("batch")
    job.add_argument("job_file")

    link = commands.add_parser("link")
    link.add_argument("reference")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_formats:
        print("\n".join(config.ALLOWED_FORMATS))
        return 0
    if args.command == "export":
        rows = filter_rows(load_ledger(args.input), args.currency)
        sys.stdout.write(REGISTRY[args.format](rows, summary_row=args.summary_row))
        return 0
    if args.command == "summary":
        rows = load_ledger(args.input)
        total = sum(row["amount"] for row in rows)
        print(f"entries: {len(rows)}")
        print(f"total: {round_display_amount(total)}")
        return 0
    if args.command == "batch":
        batch.run_job(args.job_file)
        return 0
    if args.command == "link":
        print(to_url_token(args.reference))
        return 0
    parser.print_help()
    return 2
