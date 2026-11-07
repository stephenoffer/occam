"""Warnings for a planned roster, before it goes to site.

These are company rostering rules, separate from pay: they say what we're willing to plan, not
how hours are paid. Each warning names the worker and the day.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

MIN_REST_HOURS = 11          # between the end of one shift and the start of the next
MAX_SHIFT_HOURS = 12         # paid time in one shift
MAX_CONSECUTIVE_DAYS = 6
MAX_PLANNED_WEEK_HOURS = 60  # company cap on a planned week, well inside the 48-hour average


def _span(row: dict[str, str]) -> tuple[datetime, datetime, float]:
    day = date.fromisoformat(row["date"])
    start = datetime.combine(day, datetime.strptime(row["start"], "%H:%M").time())
    end = datetime.combine(day, datetime.strptime(row["end"], "%H:%M").time())
    paid = (end - start).total_seconds() / 3600 - int(row.get("unpaid_break_minutes") or 0) / 60
    return start, end, paid


def warnings(rows: list[dict[str, str]]) -> list[str]:
    found: list[str] = []
    by_worker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["worker_id"] and row["worker_id"] != "VACANT":
            by_worker[row["worker_id"]].append(row)
    for worker, worker_rows in sorted(by_worker.items()):
        spans = sorted((_span(row) for row in worker_rows), key=lambda span: span[0])
        week_hours: dict[date, float] = defaultdict(float)
        streak, previous_day = 0, None
        for index, (start, end, paid) in enumerate(spans):
            day = start.date()
            if paid > MAX_SHIFT_HOURS:
                found.append(f"{worker} {day}: {paid:g} paid hours in one shift (limit {MAX_SHIFT_HOURS})")
            if index:
                rest = (start - spans[index - 1][1]).total_seconds() / 3600
                if rest < MIN_REST_HOURS:
                    found.append(f"{worker} {day}: only {rest:g} hours' rest before this shift")
            streak = streak + 1 if previous_day == day - timedelta(days=1) else (streak if previous_day == day else 1)
            if streak > MAX_CONSECUTIVE_DAYS:
                found.append(f"{worker} {day}: day {streak} in a row")
            previous_day = day
            week_hours[day - timedelta(days=day.weekday())] += paid
        for monday, hours in sorted(week_hours.items()):
            if hours > MAX_PLANNED_WEEK_HOURS:
                found.append(f"{worker} week of {monday}: {hours:g} planned hours (cap {MAX_PLANNED_WEEK_HOURS})")
    return found
