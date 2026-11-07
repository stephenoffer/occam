"""The monthly clinic figures.

The arithmetic that decides what counts as what lives in the SQL beside this module, so
the practice manager can run the same queries by hand against a copy of the database.
This module only adds the rates and the totals.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from common.clock import month_bounds

SQL = Path(__file__).with_name("sql")
COUNTS = ("booked", "attended", "cancellations", "dna", "treatment_minutes")


def dna_rate(attended: int, dna: int) -> float | None:
    """Share of appointments that went ahead or should have, that the patient did not attend."""
    expected = attended + dna
    return round(dna / expected, 3) if expected else None


@dataclass
class MonthlyFigures:
    month: str
    clinicians: list[dict] = field(default_factory=list)
    new_patients: int = 0

    @property
    def totals(self) -> dict:
        totals = {name: sum(row[name] for row in self.clinicians) for name in COUNTS}
        totals["dna_rate"] = dna_rate(totals["attended"], totals["dna"])
        return totals

    def as_dict(self) -> dict:
        return {"month": self.month, "clinicians": self.clinicians, "totals": self.totals,
                "new_patients": self.new_patients}


def monthly(db: sqlite3.Connection, month: str) -> MonthlyFigures:
    start, end = month_bounds(month)
    bounds = {"month_start": start, "month_end": end}
    figures = MonthlyFigures(month)
    for row in db.execute((SQL / "clinician_month.sql").read_text(), bounds):
        entry = {key: row[key] for key in row.keys()}
        entry["dna_rate"] = dna_rate(entry["attended"], entry["dna"])
        figures.clinicians.append(entry)
    figures.new_patients = db.execute((SQL / "new_patients.sql").read_text(), bounds).fetchone()["new_patients"]
    return figures
