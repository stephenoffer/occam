"""Business day arithmetic for rentals."""

from datetime import date, timedelta

HOLIDAYS = frozenset({
    date(2026, 1, 1),
    date(2026, 5, 25),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
})


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS


def next_business_day(day: date) -> date:
    day += timedelta(days=1)
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def previous_business_day(day: date) -> date:
    day -= timedelta(days=1)
    while not is_business_day(day):
        day -= timedelta(days=1)
    return day


def business_days_between(start: date, end: date) -> int:
    """Business days after `start`, up to and including `end`."""
    if end <= start:
        return 0
    weeks, extra = divmod((end - start).days, 7)
    days = weeks * 5 + extra
    if extra and start.weekday() + extra >= 5:
        days -= 2
    holidays = sum(1 for holiday in HOLIDAYS if start < holiday <= end and holiday.weekday() < 5)
    return max(0, days - holidays)
