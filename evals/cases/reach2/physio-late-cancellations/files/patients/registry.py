"""Registering patients and looking them up."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date

from patients.phone import normalise

FUNDING = ("self", "insurer")


@dataclass(frozen=True)
class Patient:
    id: int
    name: str
    phone: str | None
    email: str | None
    funding: str
    registered_on: str

    def as_dict(self) -> dict:
        return asdict(self)


def register(db: sqlite3.Connection, name: str, on: date, phone: str | None = None, email: str | None = None,
             funding: str = "self") -> Patient:
    if not name.strip():
        raise ValueError("a patient needs a name")
    if funding not in FUNDING:
        raise ValueError(f"funding must be one of {', '.join(FUNDING)}")
    number = normalise(phone) if phone else None
    with db:
        cursor = db.execute(
            "INSERT INTO patients (name, phone, email, funding, registered_on) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), number, email, funding, on.isoformat()),
        )
    return get(db, cursor.lastrowid)


def get(db: sqlite3.Connection, patient_id: int) -> Patient:
    row = db.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    if row is None:
        raise LookupError(f"no patient {patient_id}")
    return Patient(row["id"], row["name"], row["phone"], row["email"], row["funding"], row["registered_on"])


def find(db: sqlite3.Connection, text: str) -> list[Patient]:
    """Patients whose name contains ``text``, ignoring case."""
    rows = db.execute("SELECT id FROM patients WHERE name LIKE ? ORDER BY name", (f"%{text}%",))
    return [get(db, row["id"]) for row in rows]
