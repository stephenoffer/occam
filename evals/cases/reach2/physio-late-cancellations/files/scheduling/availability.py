"""Which slots a clinician has free.

A slot is free when it lies inside one of the clinician's sessions and no appointment
holds any part of it. Every appointment holds its time unless its status gives the time
back; completed and missed appointments keep it, since the clinician's time was spent.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from appointments.queries import Appointment, for_clinician_between
from appointments.status import Status
from common.clock import day_bounds
from scheduling.sessions import sessions_for, slot_starts, within_sessions

RELEASES_SLOT = frozenset({Status.CANCELLED})


def slot_minutes(db: sqlite3.Connection, clinician_id: int) -> int:
    row = db.execute("SELECT slot_minutes FROM clinicians WHERE id = ?", (clinician_id,)).fetchone()
    if row is None:
        raise LookupError(f"no clinician {clinician_id}")
    return row["slot_minutes"]


def holding(db: sqlite3.Connection, clinician_id: int, day: date) -> list[Appointment]:
    """Appointments that hold time in the clinician's diary on ``day``."""
    start, end = day_bounds(day)
    return [a for a in for_clinician_between(db, clinician_id, start, end) if a.status not in RELEASES_SLOT]


def _overlaps(starts_at: datetime, minutes: int, appointment: Appointment) -> bool:
    ends_at = starts_at + timedelta(minutes=minutes)
    return starts_at < appointment.ends_at and appointment.starts_at < ends_at


def is_free(db: sqlite3.Connection, clinician_id: int, starts_at: datetime, minutes: int) -> bool:
    if not within_sessions(db, clinician_id, starts_at, minutes):
        return False
    return not any(_overlaps(starts_at, minutes, a) for a in holding(db, clinician_id, starts_at.date()))


def free_slots(db: sqlite3.Connection, clinician_id: int, day: date) -> list[datetime]:
    minutes = slot_minutes(db, clinician_id)
    taken = holding(db, clinician_id, day)
    free = []
    for session in sessions_for(db, clinician_id, day):
        for start in slot_starts(session, day, minutes):
            if not any(_overlaps(start, minutes, a) for a in taken):
                free.append(start)
    return free
