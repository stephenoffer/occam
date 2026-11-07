"""Pay weeks run Monday to Sunday and are named by their Monday."""

from __future__ import annotations

import calendar
from datetime import date, timedelta


class WeekError(ValueError):
    pass


def week_start(day: date) -> date:
    """The Monday of the pay week containing ``day``."""
    return day - timedelta(days=day.weekday())


def week_days(start: date) -> list[date]:
    if start.weekday() != 0:
        raise WeekError(f"{start} is not a Monday")
    return [start + timedelta(days=offset) for offset in range(7)]


def parse_week(text: str) -> date:
    """Parse a pay week given as the ISO date of its Monday."""
    try:
        start = date.fromisoformat(text)
    except ValueError as exc:
        raise WeekError(f"not a date: {text!r}") from exc
    if start.weekday() != 0:
        raise WeekError(f"pay weeks start on a Monday; {text} is a {calendar.day_name[start.weekday()]}")
    return start


def weeks_starting_in(year: int, month: int) -> list[date]:
    """Every Monday that falls in the given calendar month."""
    first = date(year, month, 1)
    monday = first + timedelta(days=(7 - first.weekday()) % 7)
    weeks = []
    while monday.month == month:
        weeks.append(monday)
        monday += timedelta(days=7)
    return weeks


def parse_month(text: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in text.split("-"))
    except ValueError as exc:
        raise WeekError(f"months are written YYYY-MM, not {text!r}") from exc
    if not 1 <= month <= 12:
        raise WeekError(f"no month {month}")
    return year, month
