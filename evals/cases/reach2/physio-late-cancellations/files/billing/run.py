"""The nightly charge run.

Cron runs it at 02:00 (docs/runbook.md). Each kind of charge has a query in billing/sql
that finds what is due and not charged yet, and the run raises one charge per row it
returns. Running it twice is harmless: the queries skip anything already charged, and the
charges table allows one charge per appointment and kind.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from billing.fees import FeeSchedule
from common.clock import stored

SQL = Path(__file__).with_name("sql")

# Charge kind -> the query that finds what is due.
DUE = {
    "treatment": "treatment_fees.sql",
    "dna": "dna_fees.sql",
}


@dataclass(frozen=True)
class Charge:
    appointment_id: int
    patient_id: int
    kind: str
    amount_pence: int
    raised_at: str

    def as_dict(self) -> dict:
        return asdict(self)


def _amount(kind: str, row: sqlite3.Row, fees: FeeSchedule) -> int:
    if kind == "treatment":
        return fees.treatment_for(row["minutes"])
    if kind == "dna":
        return fees.missed_appointment_pence
    raise ValueError(f"no fee for charge kind {kind!r}")


def due(db: sqlite3.Connection, kind: str, run_at: datetime) -> list[sqlite3.Row]:
    query = (SQL / DUE[kind]).read_text()
    return db.execute(query, {"run_at": stored(run_at)}).fetchall()


def run_charges(db: sqlite3.Connection, run_at: datetime, fees: FeeSchedule) -> list[Charge]:
    raised: list[Charge] = []
    with db:
        for kind in DUE:
            for row in due(db, kind, run_at):
                charge = Charge(row["appointment_id"], row["patient_id"], kind, _amount(kind, row, fees), stored(run_at))
                db.execute(
                    "INSERT INTO charges (appointment_id, patient_id, kind, amount_pence, raised_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (charge.appointment_id, charge.patient_id, charge.kind, charge.amount_pence, charge.raised_at),
                )
                raised.append(charge)
    return raised
