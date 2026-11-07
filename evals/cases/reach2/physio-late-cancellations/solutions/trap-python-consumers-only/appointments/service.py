"""The appointment lifecycle: book, confirm, arrive, complete, cancel and no-show.

Each change updates ``appointments`` and appends to ``appointment_events`` in one
transaction, so the history of an appointment can always be replayed. Messages to the
patient are queued after the change is committed; a failure to queue never undoes it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from appointments import queries
from appointments.errors import InvalidMove, SlotUnavailable, TooEarly, TooLate
from appointments.queries import Appointment
from appointments.status import Status, can_move
from common.clock import stored
from messaging.outbox import queue_for_appointment
from scheduling.availability import is_free, slot_minutes

# Patients may be checked in this long before their start time.
EARLY_ARRIVAL = timedelta(minutes=60)

# Cancelling with less notice than this is a late cancellation.
LATE_CANCELLATION_NOTICE = timedelta(hours=24)


def book(db: sqlite3.Connection, patient_id: int, clinician_id: int, starts_at: datetime, at: datetime,
         minutes: int | None = None) -> Appointment:
    if starts_at <= at:
        raise TooLate("appointments can only be booked in the future")
    minutes = minutes or slot_minutes(db, clinician_id)
    if not is_free(db, clinician_id, starts_at, minutes):
        raise SlotUnavailable(f"clinician {clinician_id} isn't free at {stored(starts_at)} for {minutes} minutes")
    with db:
        cursor = db.execute(
            "INSERT INTO appointments (patient_id, clinician_id, starts_at, minutes, status, booked_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (patient_id, clinician_id, stored(starts_at), minutes, int(Status.BOOKED), stored(at), stored(at)),
        )
        _record(db, cursor.lastrowid, Status.BOOKED, at)
    appointment = queries.get(db, cursor.lastrowid)
    queue_for_appointment(db, appointment, "booked", at)
    return appointment


def confirm(db: sqlite3.Connection, appointment_id: int, at: datetime) -> Appointment:
    appointment = queries.get(db, appointment_id)
    if at >= appointment.starts_at:
        raise TooLate("only appointments that haven't started can be confirmed")
    return _move(db, appointment, Status.CONFIRMED, at)


def arrive(db: sqlite3.Connection, appointment_id: int, at: datetime) -> Appointment:
    appointment = queries.get(db, appointment_id)
    if at < appointment.starts_at - EARLY_ARRIVAL:
        raise TooEarly("too early to check this patient in")
    return _move(db, appointment, Status.ARRIVED, at)


def complete(db: sqlite3.Connection, appointment_id: int, at: datetime) -> Appointment:
    return _move(db, queries.get(db, appointment_id), Status.COMPLETED, at)


def cancel(db: sqlite3.Connection, appointment_id: int, at: datetime) -> Appointment:
    """Cancel an appointment that hasn't started yet, at the patient's or the clinic's request.

    With less than a day's notice it becomes a late cancellation, which frees the slot but
    otherwise counts as a no-show.
    """
    appointment = queries.get(db, appointment_id)
    if at >= appointment.starts_at:
        raise TooLate("the appointment has already started: record a no-show instead")
    late = appointment.starts_at - at < LATE_CANCELLATION_NOTICE
    target = Status.LATE_CANCELLED if late else Status.CANCELLED
    cancelled = _move(db, appointment, target, at, cancelled_at=at)
    queue_for_appointment(db, cancelled, "cancelled", at)
    return cancelled


def mark_no_show(db: sqlite3.Connection, appointment_id: int, at: datetime) -> Appointment:
    appointment = queries.get(db, appointment_id)
    if at < appointment.starts_at:
        raise TooEarly("an appointment can't be missed before it starts")
    return _move(db, appointment, Status.NO_SHOW, at)


def _move(db: sqlite3.Connection, appointment: Appointment, target: Status, at: datetime,
          **times: datetime) -> Appointment:
    if not can_move(appointment.status, target):
        raise InvalidMove(f"appointment {appointment.id} is {appointment.status.label} and can't become {target.label}")
    columns = ["status", "updated_at", *times]
    values = [int(target), stored(at), *(stored(value) for value in times.values())]
    assignments = ", ".join(f"{column} = ?" for column in columns)
    with db:
        db.execute(f"UPDATE appointments SET {assignments} WHERE id = ?", (*values, appointment.id))
        _record(db, appointment.id, target, at)
    return queries.get(db, appointment.id)


def _record(db: sqlite3.Connection, appointment_id: int, status: Status, at: datetime) -> None:
    db.execute("INSERT INTO appointment_events (appointment_id, status, at) VALUES (?, ?, ?)",
               (appointment_id, int(status), stored(at)))
