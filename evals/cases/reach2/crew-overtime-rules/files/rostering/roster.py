"""Expanding patterns into a planned roster, in the CSV layout costing reads."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

from common.csvio import read_rows, write_rows
from rostering.patterns import get

FIELDS = ["site", "worker_id", "date", "start", "end", "unpaid_break_minutes"]


def expand(pattern_name: str, worker_id: str, site: str, first: date, weeks: int) -> list[dict[str, str]]:
    pattern = get(pattern_name)
    return [{
        "site": site,
        "worker_id": worker_id,
        "date": day.isoformat(),
        "start": slot.start.strftime("%H:%M"),
        "end": slot.end.strftime("%H:%M"),
        "unpaid_break_minutes": str(slot.unpaid_break_minutes),
    } for day, slot in pattern.shifts_between(first, weeks * 7)]


def append_rows(path: str | Path, rows: Iterable[dict[str, str]]) -> int:
    path = Path(path)
    existing = read_rows(path, FIELDS) if path.exists() else []
    combined = [{key: row[key] for key in FIELDS} for row in existing] + list(rows)
    combined.sort(key=lambda row: (row["site"], row["date"], row["start"], row["worker_id"]))
    write_rows(path, FIELDS, combined)
    return len(combined)
