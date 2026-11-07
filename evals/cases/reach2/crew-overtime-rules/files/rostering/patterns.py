"""Named shift patterns site managers roster from.

Weekly patterns list (weekday, start, end, unpaid break minutes) with Monday as 0. Cycle patterns
repeat every ``length`` days from the roster's start date, whatever the weekday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta


@dataclass(frozen=True)
class Slot:
    start: time
    end: time
    unpaid_break_minutes: int


@dataclass(frozen=True)
class WeeklyPattern:
    name: str
    slots: dict[int, Slot]

    def shifts_between(self, first: date, days: int) -> list[tuple[date, Slot]]:
        out = []
        for offset in range(days):
            day = first + timedelta(days=offset)
            if day.weekday() in self.slots:
                out.append((day, self.slots[day.weekday()]))
        return out


@dataclass(frozen=True)
class CyclePattern:
    name: str
    length: int
    on_days: tuple[int, ...]
    slot: Slot

    def shifts_between(self, first: date, days: int) -> list[tuple[date, Slot]]:
        return [(first + timedelta(days=offset), self.slot) for offset in range(days)
                if offset % self.length in self.on_days]


def _weekly(name: str, weekdays: range | tuple[int, ...], start: str, end: str, unpaid: int) -> WeeklyPattern:
    slot = Slot(time.fromisoformat(start), time.fromisoformat(end), unpaid)
    return WeeklyPattern(name, {day: slot for day in weekdays})


PATTERNS = {
    pattern.name: pattern
    for pattern in [
        _weekly("days", range(0, 5), "07:30", "16:00", 30),
        _weekly("earlies", range(0, 5), "06:00", "14:00", 30),
        _weekly("long-days", range(0, 4), "07:00", "17:30", 30),
        _weekly("weekend-cover", (5, 6), "08:00", "18:30", 30),
        CyclePattern("four-on-four-off", 8, (0, 1, 2, 3), Slot(time(7, 0), time(19, 0), 60)),
    ]
}


def get(name: str):
    try:
        return PATTERNS[name]
    except KeyError:
        raise KeyError(f"unknown pattern {name!r}; known: {', '.join(sorted(PATTERNS))}") from None
