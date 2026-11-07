"""The evening reminder run: one text per appointment tomorrow that is still going ahead."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from appointments.queries import from_row
from appointments.status import UPCOMING
from common.clock import day_bounds
from messaging.outbox import queue_for_appointment


def due_reminders(db: sqlite3.Connection, now: datetime) -> list:
    start, end = day_bounds(now.date() + timedelta(days=1))
    rows = db.execute(
        "SELECT a.* FROM appointments a"
        " WHERE a.starts_at >= ? AND a.starts_at < ?"
        " AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.appointment_id = a.id AND m.template = 'reminder')"
        " ORDER BY a.starts_at",
        (start, end),
    )
    return [appointment for appointment in map(from_row, rows) if appointment.status in UPCOMING]


def send_reminders(db: sqlite3.Connection, now: datetime) -> list[int]:
    queued = []
    for appointment in due_reminders(db, now):
        message_id = queue_for_appointment(db, appointment, "reminder", now)
        if message_id is not None:
            queued.append(message_id)
    return queued
