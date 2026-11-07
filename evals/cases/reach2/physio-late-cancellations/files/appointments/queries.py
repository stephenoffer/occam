"""Read-only lookups over the appointments table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from appointments.errors import NotFound
from appointments.status import Status
from common.clock import parse_at


@dataclass(frozen=True)
class Appointment:
    id: int
    patient_id: int
    clinician_id: int
    starts_at: datetime
    minutes: int
    status: Status
    booked_at: datetime
    cancelled_at: datetime | None

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.minutes)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "clinician_id": self.clinician_id,
            "starts_at": self.starts_at.isoformat(timespec="minutes"),
            "minutes": self.minutes,
            "status": self.status.label,
            "booked_at": self.booked_at.isoformat(timespec="minutes"),
            "cancelled_at": self.cancelled_at.isoformat(timespec="minutes") if self.cancelled_at else None,
        }


def from_row(row: sqlite3.Row) -> Appointment:
    return Appointment(
        id=row["id"],
        patient_id=row["patient_id"],
        clinician_id=row["clinician_id"],
        starts_at=parse_at(row["starts_at"]),
        minutes=row["minutes"],
        status=Status(row["status"]),
        booked_at=parse_at(row["booked_at"]),
        cancelled_at=parse_at(row["cancelled_at"]) if row["cancelled_at"] else None,
    )


def get(db: sqlite3.Connection, appointment_id: int) -> Appointment:
    row = db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    if row is None:
        raise NotFound(f"no appointment {appointment_id}")
    return from_row(row)


def for_patient(db: sqlite3.Connection, patient_id: int) -> list[Appointment]:
    rows = db.execute("SELECT * FROM appointments WHERE patient_id = ? ORDER BY starts_at, id", (patient_id,))
    return [from_row(row) for row in rows]


def for_clinician_between(db: sqlite3.Connection, clinician_id: int, start: str, end: str) -> list[Appointment]:
    """Appointments for one clinician starting in [start, end), any status."""
    rows = db.execute(
        "SELECT * FROM appointments WHERE clinician_id = ? AND starts_at >= ? AND starts_at < ? ORDER BY starts_at",
        (clinician_id, start, end),
    )
    return [from_row(row) for row in rows]


def events(db: sqlite3.Connection, appointment_id: int) -> list[tuple[Status, str]]:
    rows = db.execute("SELECT status, at FROM appointment_events WHERE appointment_id = ? ORDER BY id",
                      (appointment_id,))
    return [(Status(row["status"]), row["at"]) for row in rows]
