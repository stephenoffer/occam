"""    python -m payroll run ... --json > payslips.json
    python -m exports bureau --payslips payslips.json --out PAYIMP.txt
"""

from __future__ import annotations

import argparse
import sys

from exports.bureau import BureauError, write


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m exports")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("bureau", help="write the bureau's fixed-width import")
    cmd.add_argument("--payslips", required=True)
    cmd.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        count = write(args.payslips, args.out)
    except (BureauError, KeyError, OSError, ValueError) as exc:
        print(f"exports: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {count} records to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
