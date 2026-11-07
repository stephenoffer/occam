"""Loading a planned roster and the base rates to price it with.

Roster columns: site, worker_id, date, start, end, unpaid_break_minutes. A worker_id of ``VACANT``
is a shift nobody has been assigned to yet; it is priced at the vacant rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from common.csvio import CsvError, read_rows
from common.money import parse_money

VACANT = "VACANT"


@dataclass(frozen=True)
class PlannedShift:
    site: str
    worker_id: str
    day: date
    start: time
    end: time
    unpaid_break_minutes: int = 0

    @property
    def hours(self) -> Decimal:
        """Planned hours. Plans are drawn in quarter hours already, so no rounding is applied."""
        minutes = (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)
        return Decimal(minutes - self.unpaid_break_minutes) / Decimal(60)

    @property
    def vacant(self) -> bool:
        return self.worker_id == VACANT


def _clock(text: str, where: str) -> time:
    try:
        hh, mm = text.split(":")
        return time(int(hh), int(mm))
    except ValueError as exc:
        raise CsvError(f"{where}: bad time {text!r}") from exc


def load_roster(path: str | Path) -> list[PlannedShift]:
    shifts = []
    for row in read_rows(path, ["site", "worker_id", "date", "start", "end"]):
        where = f"{path}:{row['_line']}"
        try:
            day = date.fromisoformat(row["date"])
            unpaid = int(row.get("unpaid_break_minutes") or 0)
        except ValueError as exc:
            raise CsvError(f"{where}: {exc}") from exc
        shift = PlannedShift(row["site"], row["worker_id"] or VACANT, day, _clock(row["start"], where),
                             _clock(row["end"], where), unpaid)
        if shift.hours <= 0:
            raise CsvError(f"{where}: shift has no paid time")
        shifts.append(shift)
    return shifts


def load_base_rates(path: str | Path) -> dict[str, Decimal]:
    """Only the columns costing needs from the rates file payroll also reads."""
    return {row["worker_id"]: parse_money(row["base_hourly"]) for row in read_rows(path, ["worker_id", "base_hourly"])}
