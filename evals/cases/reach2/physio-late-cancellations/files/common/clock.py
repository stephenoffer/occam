"""Clinic times.

Every time in the system is a naive local (UK) wall-clock time, stored as an ISO string to the
minute: ``2026-12-08T10:00``. See docs/adr/0002-naive-local-times.md for why there are no time zones.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

STORED_FORMAT = "%Y-%m-%dT%H:%M"


def parse_at(text: str) -> datetime:
    """Parse a stored or user-supplied time. Seconds are accepted and dropped."""
    value = datetime.fromisoformat(text.strip())
    if value.tzinfo is not None:
        raise ValueError(f"times are local wall-clock times, got an offset: {text!r}")
    return value.replace(second=0, microsecond=0)


def stored(value: datetime) -> str:
    return value.strftime(STORED_FORMAT)


def parse_day(text: str) -> date:
    return date.fromisoformat(text.strip())


def day_bounds(day: date) -> tuple[str, str]:
    """The stored-string range [start, end) covering one calendar day."""
    start = datetime.combine(day, datetime.min.time())
    return stored(start), stored(start + timedelta(days=1))


def month_bounds(month: str) -> tuple[str, str]:
    """The stored-string range [start, end) for a month given as ``YYYY-MM``."""
    year, number = (int(part) for part in month.split("-"))
    if not 1 <= number <= 12:
        raise ValueError(f"not a month: {month!r}")
    start = datetime(year, number, 1)
    end = datetime(year + (number == 12), number % 12 + 1, 1)
    return stored(start), stored(end)


def at_time(day: date, hhmm: str) -> datetime:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return datetime.combine(day, datetime.min.time()).replace(hour=hours, minute=minutes)


def human(value: datetime) -> str:
    """How a time reads in a text message: ``Tue 8 Dec at 10:00``."""
    return f"{value:%a} {value.day} {value:%b} at {value:%H:%M}"
