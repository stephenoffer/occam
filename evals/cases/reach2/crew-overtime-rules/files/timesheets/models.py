from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

from timesheets.rounding import to_quarter_hours

APPROVED = "approved"
STATUSES = {"draft", "submitted", APPROVED, "rejected"}


def minutes_of(moment: time) -> int:
    return moment.hour * 60 + moment.minute


@dataclass(frozen=True)
class Shift:
    """One shift as recorded by the site app. Shifts never cross midnight: night work is split at 00:00."""

    worker_id: str
    work_date: date
    start: time
    end: time
    unpaid_break_minutes: int
    site: str
    cost_centre: str
    status: str = APPROVED

    @property
    def worked_minutes(self) -> int:
        return minutes_of(self.end) - minutes_of(self.start) - self.unpaid_break_minutes

    @property
    def hours(self) -> Decimal:
        return to_quarter_hours(self.worked_minutes)

    @property
    def approved(self) -> bool:
        return self.status == APPROVED
