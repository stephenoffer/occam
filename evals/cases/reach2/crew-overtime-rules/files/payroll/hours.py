"""Splitting a pay week's hours into regular hours and overtime.

Overtime is set by the site agreement: hours worked beyond 40 in a pay week
(Monday to Sunday) are overtime. Only approved shifts count. See docs/payroll.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from common.weeks import week_start
from timesheets.models import Shift

WEEKLY_OVERTIME_AFTER = Decimal(40)
ZERO = Decimal(0)


@dataclass(frozen=True)
class WeekHours:
    worker_id: str
    week: date
    regular: Decimal
    overtime: Decimal

    @property
    def total(self) -> Decimal:
        return self.regular + self.overtime


def split_week(worker_id: str, week: date, shifts: Iterable[Shift]) -> WeekHours:
    """Regular and overtime hours for one worker's pay week."""
    worked = [s for s in shifts if s.worker_id == worker_id and s.approved and week_start(s.work_date) == week]
    total = sum((s.hours for s in worked), ZERO)
    overtime = max(total - WEEKLY_OVERTIME_AFTER, ZERO)
    return WeekHours(worker_id, week, total - overtime, overtime)


def split_all(shifts: Iterable[Shift], week: date) -> dict[str, WeekHours]:
    """WeekHours for everyone with an approved shift in the week, keyed by worker id."""
    by_worker: dict[str, list[Shift]] = defaultdict(list)
    for shift in shifts:
        if shift.approved and week_start(shift.work_date) == week:
            by_worker[shift.worker_id].append(shift)
    return {worker: split_week(worker, week, worked) for worker, worked in sorted(by_worker.items())}
