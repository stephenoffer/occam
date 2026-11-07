"""Shared fixtures: an in-memory clinic with one clinician working weekdays 09:00-17:00."""

from __future__ import annotations

from datetime import datetime

import pytest

from appointments import service
from clinicdb.connect import open_db
from clinicdb.seed import load_seed

WEEKDAYS = [{"weekday": day, "starts": "09:00", "ends": "17:00"} for day in range(5)]

SEED = {
    "clinics": [{"id": 1, "name": "Leith Walk", "phone": "0131 496 0123"}],
    "clinicians": [
        {"id": 1, "name": "Aisha Patel", "clinic_id": 1, "slot_minutes": 45, "sessions": WEEKDAYS},
        {"id": 2, "name": "Callum Reid", "clinic_id": 1, "slot_minutes": 60,
         "sessions": [{"weekday": 1, "starts": "08:00", "ends": "12:00"}]},
    ],
    "patients": [
        {"id": 1, "name": "Fiona MacLeod", "phone": "07700 900111", "funding": "self", "registered_on": "2025-04-02"},
        {"id": 2, "name": "Daniel Okafor", "phone": "07700 900222", "funding": "insurer", "registered_on": "2025-06-19"},
        {"id": 3, "name": "Ross Henderson", "funding": "self", "registered_on": "2026-09-30"},
    ],
}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


@pytest.fixture
def db():
    connection = open_db(":memory:")
    load_seed(connection, SEED)
    yield connection
    connection.close()


@pytest.fixture
def book(db):
    def make(patient: int, start: str, booked_at: str = "2026-10-01T09:00", clinician: int = 1, minutes=None):
        return service.book(db, patient, clinician, at(start), at(booked_at), minutes)
    return make
