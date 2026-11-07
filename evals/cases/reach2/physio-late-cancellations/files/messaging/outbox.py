"""Rendering and queueing messages."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any

from common.clock import human, stored

TEMPLATES = Path(__file__).with_name("templates")


def render(template: str, **values: Any) -> str:
    return Template((TEMPLATES / f"{template}.txt").read_text().strip()).substitute(values)


def queue(db: sqlite3.Connection, patient_id: int, appointment_id: int | None, template: str, body: str,
          at: datetime) -> int:
    with db:
        cursor = db.execute(
            "INSERT INTO messages (patient_id, appointment_id, template, body, queued_at) VALUES (?, ?, ?, ?, ?)",
            (patient_id, appointment_id, template, body, stored(at)),
        )
    return cursor.lastrowid


def queue_for_appointment(db: sqlite3.Connection, appointment: Any, template: str, at: datetime) -> int | None:
    """Queue ``template`` about ``appointment``. Patients without a phone number get nothing."""
    row = db.execute(
        "SELECT p.name AS patient, p.phone AS phone, c.name AS clinician, k.name AS clinic, k.phone AS clinic_phone"
        " FROM patients p, clinicians c JOIN clinics k ON k.id = c.clinic_id"
        " WHERE p.id = ? AND c.id = ?",
        (appointment.patient_id, appointment.clinician_id),
    ).fetchone()
    if row is None or not row["phone"]:
        return None
    body = render(
        template,
        first_name=row["patient"].split()[0],
        clinician=row["clinician"],
        clinic=row["clinic"],
        clinic_phone=row["clinic_phone"] or "the clinic",
        when=human(appointment.starts_at),
    )
    return queue(db, appointment.patient_id, appointment.id, template, body, at)


def pending(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute("SELECT id, patient_id, appointment_id, template, body, queued_at FROM messages"
                      " WHERE sent_at IS NULL ORDER BY id")
    return [dict(row) for row in rows]
