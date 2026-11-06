"""Calendar helpers."""

from calendar import monthrange
from datetime import date, timedelta


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def following_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day
