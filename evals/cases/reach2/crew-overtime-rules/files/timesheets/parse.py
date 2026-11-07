"""Load the site app's timesheet export.

Columns: worker_id, work_date, start, end, unpaid_break_minutes, site, cost_centre, status.
``status`` may be omitted, in which case every row counts as approved (older exports had no status).
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

from common.csvio import CsvError, read_rows
from timesheets.models import APPROVED, STATUSES, Shift

COLUMNS = ["worker_id", "work_date", "start", "end", "unpaid_break_minutes", "site", "cost_centre"]


def _time(text: str, where: str) -> time:
    try:
        hours, minutes = text.split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise CsvError(f"{where}: bad time {text!r}") from exc


def parse_row(row: dict[str, str], where: str) -> Shift:
    try:
        work_date = date.fromisoformat(row["work_date"])
    except ValueError as exc:
        raise CsvError(f"{where}: bad date {row['work_date']!r}") from exc
    try:
        break_minutes = int(row["unpaid_break_minutes"] or 0)
    except ValueError as exc:
        raise CsvError(f"{where}: bad break {row['unpaid_break_minutes']!r}") from exc
    status = (row.get("status") or APPROVED).lower()
    if status not in STATUSES:
        raise CsvError(f"{where}: unknown status {status!r}")
    end_text = row["end"]
    if end_text == "24:00":
        end_text = "23:59"
    return Shift(
        worker_id=row["worker_id"],
        work_date=work_date,
        start=_time(row["start"], where),
        end=_time(end_text, where),
        unpaid_break_minutes=break_minutes,
        site=row["site"],
        cost_centre=row["cost_centre"],
        status=status,
    )


def load_timesheets(path: str | Path) -> list[Shift]:
    rows = read_rows(path, COLUMNS)
    return [parse_row(row, f"{path}:{row['_line']}") for row in rows]
