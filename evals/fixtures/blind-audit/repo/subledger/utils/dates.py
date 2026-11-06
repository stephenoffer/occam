"""Date helpers. Subledger works in UTC throughout."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_today() -> date:
    return utc_now().date()


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def add_months(value: date, months: int) -> date:
    """Add calendar months, clamping to the last day of a shorter month."""
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def days_inclusive(start: date, end: date) -> int:
    return (end - start).days + 1


def month_bounds(month: str) -> tuple[date, date]:
    """Return the first and last day of a 'YYYY-MM' month."""
    first = date.fromisoformat(f"{month}-01")
    return first, add_months(first, 1) - timedelta(days=1)
