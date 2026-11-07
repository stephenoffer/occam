"""Checks run before a week is paid. Each problem is a sentence a payroll clerk can act on."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from timesheets.models import Shift, minutes_of


def problems(shifts: Iterable[Shift], known_workers: set[str] | None = None) -> list[str]:
    found: list[str] = []
    by_worker_day: dict[tuple[str, object], list[Shift]] = defaultdict(list)
    for shift in shifts:
        label = f"{shift.worker_id} on {shift.work_date}"
        if minutes_of(shift.end) <= minutes_of(shift.start):
            found.append(f"{label}: shift ends at or before it starts")
            continue
        if shift.unpaid_break_minutes < 0:
            found.append(f"{label}: negative break")
        elif shift.worked_minutes <= 0:
            found.append(f"{label}: break is as long as the shift")
        if known_workers is not None and shift.worker_id not in known_workers:
            found.append(f"{label}: no pay rate on file")
        by_worker_day[(shift.worker_id, shift.work_date)].append(shift)
    for (worker, day), day_shifts in sorted(by_worker_day.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        ordered = sorted(day_shifts, key=lambda s: minutes_of(s.start))
        for earlier, later in zip(ordered, ordered[1:]):
            if minutes_of(later.start) < minutes_of(earlier.end):
                found.append(f"{worker} on {day}: shifts overlap ({earlier.start:%H:%M}-{earlier.end:%H:%M} "
                             f"and {later.start:%H:%M}-{later.end:%H:%M})")
    return found
