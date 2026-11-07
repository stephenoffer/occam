"""Builders shared by the tests."""

from __future__ import annotations

import csv
from datetime import date, time
from pathlib import Path

from timesheets.models import Shift


def shift(worker: str, day: str, start: str, end: str, unpaid: int = 0, site: str = "QSY",
          cost_centre: str = "CC-420", status: str = "approved") -> Shift:
    return Shift(worker, date.fromisoformat(day), time.fromisoformat(start), time.fromisoformat(end), unpaid, site,
                 cost_centre, status)


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


TIMESHEET_HEADER = ["worker_id", "work_date", "start", "end", "unpaid_break_minutes", "site", "cost_centre", "status"]
ROSTER_HEADER = ["site", "worker_id", "date", "start", "end", "unpaid_break_minutes"]
RATES_HEADER = ["worker_id", "name", "grade", "base_hourly"]
