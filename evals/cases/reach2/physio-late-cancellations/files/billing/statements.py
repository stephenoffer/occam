"""Patient statements: what we've charged a patient and for what."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from common.money import pounds

STATEMENT_SQL = Path(__file__).with_name("sql") / "statement.sql"

DESCRIPTIONS = {
    "treatment": "Treatment session",
    "dna": "Missed appointment fee",
}


@dataclass
class Statement:
    patient_id: int
    lines: list[dict] = field(default_factory=list)

    @property
    def total_pence(self) -> int:
        return sum(line["amount_pence"] for line in self.lines)

    def as_dict(self) -> dict:
        return {"patient_id": self.patient_id, "lines": self.lines, "total_pence": self.total_pence}

    def render(self) -> str:
        rows = [f"{line['starts_at'][:10]}  {line['description']:<26} {pounds(line['amount_pence']):>10}"
                for line in self.lines]
        rows.append(f"{'':10}  {'Total':<26} {pounds(self.total_pence):>10}")
        return "\n".join(rows)


def statement(db: sqlite3.Connection, patient_id: int) -> Statement:
    built = Statement(patient_id)
    for row in db.execute(STATEMENT_SQL.read_text(), {"patient_id": patient_id}):
        built.lines.append({
            "charge_id": row["charge_id"],
            "appointment_id": row["appointment_id"],
            "starts_at": row["starts_at"],
            "kind": row["kind"],
            "description": DESCRIPTIONS.get(row["kind"], row["kind"]),
            "amount_pence": row["amount_pence"],
        })
    return built
