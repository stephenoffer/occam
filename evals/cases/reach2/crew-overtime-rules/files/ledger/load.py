"""Loading the accrual's inputs into a fresh in-memory SQLite database."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from common.csvio import CsvError, read_rows
from common.money import parse_money
from timesheets.models import Shift, minutes_of


SQL_DIR = Path(__file__).resolve().parent / "sql"


def sql_text(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(sql_text("schema.sql"))
    return conn


def load_shifts(conn: sqlite3.Connection, shifts: Iterable[Shift]) -> int:
    rows = [(s.worker_id, s.work_date.isoformat(), minutes_of(s.start), minutes_of(s.end), s.unpaid_break_minutes,
             s.site, s.cost_centre, s.status) for s in shifts]
    conn.executemany("INSERT INTO shifts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def load_rates(conn: sqlite3.Connection, path: str | Path) -> int:
    rows = []
    for row in read_rows(path, ["worker_id", "base_hourly"]):
        pence = parse_money(row["base_hourly"]) * 100
        if pence != pence.to_integral_value():
            raise CsvError(f"{path}:{row['_line']}: base rate has fractions of a penny")
        rows.append((row["worker_id"], int(pence)))
    conn.executemany("INSERT INTO rates VALUES (?, ?)", rows)
    return len(rows)


def load_weeks(conn: sqlite3.Connection, weeks: Iterable[date]) -> None:
    conn.executemany("INSERT INTO weeks VALUES (?)", [(week.isoformat(),) for week in weeks])


def pounds(pence: int) -> Decimal:
    return Decimal(pence) / 100
