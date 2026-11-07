"""Load clinics, clinicians, their sessions and patients from a JSON document.

The document has the shape of data/demo_seed.json. Ids are kept as given so that
seeded data can be referred to from scripts and tests.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def load_seed(db: sqlite3.Connection, data: dict[str, Any]) -> dict[str, int]:
    counts = {"clinics": 0, "clinicians": 0, "sessions": 0, "patients": 0}
    with db:
        for clinic in data.get("clinics", []):
            db.execute("INSERT INTO clinics (id, name, phone) VALUES (?, ?, ?)",
                       (clinic["id"], clinic["name"], clinic.get("phone")))
            counts["clinics"] += 1
        for clinician in data.get("clinicians", []):
            db.execute(
                "INSERT INTO clinicians (id, name, clinic_id, slot_minutes, active) VALUES (?, ?, ?, ?, ?)",
                (clinician["id"], clinician["name"], clinician["clinic_id"],
                 clinician.get("slot_minutes", 45), int(clinician.get("active", True))),
            )
            counts["clinicians"] += 1
            for session in clinician.get("sessions", []):
                db.execute("INSERT INTO sessions (clinician_id, weekday, starts, ends) VALUES (?, ?, ?, ?)",
                           (clinician["id"], session["weekday"], session["starts"], session["ends"]))
                counts["sessions"] += 1
        for patient in data.get("patients", []):
            db.execute(
                "INSERT INTO patients (id, name, phone, email, funding, registered_on) VALUES (?, ?, ?, ?, ?, ?)",
                (patient["id"], patient["name"], patient.get("phone"), patient.get("email"),
                 patient.get("funding", "self"), patient["registered_on"]),
            )
            counts["patients"] += 1
    return counts


def load_seed_file(db: sqlite3.Connection, path: str | Path) -> dict[str, int]:
    return load_seed(db, json.loads(Path(path).read_text()))
