"""python -m reports --db PATH monthly --month YYYY-MM [--json]"""

from __future__ import annotations

import sys

from clinicdb.connect import open_db
from common.cli import add_json_flag, emit, fail, parser
from reports.monthly import monthly
from reports.render import render


def main(argv: list[str] | None = None) -> int:
    top = parser("reports", "Clinic figures.")
    commands = top.add_subparsers(dest="command", required=True)
    month = commands.add_parser("monthly", help="figures per clinician for one month")
    month.add_argument("--month", required=True, help="YYYY-MM")
    add_json_flag(month)
    args = top.parse_args(argv)

    db = open_db(args.db)
    try:
        figures = monthly(db, args.month)
    except ValueError as error:
        return fail(str(error))
    emit(figures.as_dict(), args.json, render(figures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
