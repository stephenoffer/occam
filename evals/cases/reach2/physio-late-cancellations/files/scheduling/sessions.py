"""Weekly working patterns.

A clinician works one or more sessions on a weekday, for example 09:00-13:00 and
14:00-17:30. Bank holidays and leave are handled by reception blocking the time with a
placeholder booking, so they don't appear here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from common.clock import at_time


@dataclass(frozen=True)
class Session:
    weekday: int
    starts: str
    ends: str

    def on(self, day: date) -> tuple[datetime, datetime]:
        return at_time(day, self.starts), at_time(day, self.ends)


def sessions_for(db: sqlite3.Connection, clinician_id: int, day: date) -> list[Session]:
    rows = db.execute(
        "SELECT weekday, starts, ends FROM sessions WHERE clinician_id = ? AND weekday = ? ORDER BY starts",
        (clinician_id, day.weekday()),
    )
    return [Session(row["weekday"], row["starts"], row["ends"]) for row in rows]


def slot_starts(session: Session, day: date, minutes: int) -> list[datetime]:
    """Start times of the whole slots that fit in a session."""
    start, end = session.on(day)
    step = timedelta(minutes=minutes)
    starts = []
    while start + step <= end:
        starts.append(start)
        start += step
    return starts


def within_sessions(db: sqlite3.Connection, clinician_id: int, starts_at: datetime, minutes: int) -> bool:
    ends_at = starts_at + timedelta(minutes=minutes)
    for session in sessions_for(db, clinician_id, starts_at.date()):
        start, end = session.on(starts_at.date())
        if start <= starts_at and ends_at <= end:
            return True
    return False
