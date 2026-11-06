#!/usr/bin/env python3
"""Print invoice totals from a billing export as CSV."""

import csv
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

QUERY = Path(__file__).parent / "sql" / "invoice_totals.sql"


def main(argv):
    if len(argv) != 2:
        print(f"usage: {argv[0]} EXPORT.sqlite3", file=sys.stderr)
        return 2
    with closing(sqlite3.connect(argv[1])) as connection:
        cursor = connection.execute(QUERY.read_text())
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(column[0] for column in cursor.description)
        writer.writerows(cursor)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
