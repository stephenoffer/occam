"""Who has to pay a deposit to book online.

A patient who has had two or more no-shows in the last year pays a deposit when booking
through the website. Late cancellations count as no-shows here. Reception can still book
them by phone without one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from appointments.status import MISSED
from common.clock import stored

DEPOSIT_AFTER_NO_SHOWS = 2
LOOKBACK = timedelta(days=365)


@dataclass(frozen=True)
class DepositDecision:
    patient_id: int
    needs_deposit: bool
    no_shows: int
    since: str

    def as_dict(self) -> dict:
        return asdict(self)


def no_shows_since(db: sqlite3.Connection, patient_id: int, since: datetime, until: datetime) -> int:
    codes = sorted(int(status) for status in MISSED)
    placeholders = ", ".join("?" for _ in codes)
    row = db.execute(
        "SELECT COUNT(*) AS n FROM appointments"
        f" WHERE patient_id = ? AND status IN ({placeholders}) AND starts_at >= ? AND starts_at < ?",
        (patient_id, *codes, stored(since), stored(until)),
    ).fetchone()
    return row["n"]


def deposit_decision(db: sqlite3.Connection, patient_id: int, on: date) -> DepositDecision:
    until = datetime.combine(on + timedelta(days=1), datetime.min.time())
    since = until - LOOKBACK
    count = no_shows_since(db, patient_id, since, until)
    return DepositDecision(patient_id, count >= DEPOSIT_AFTER_NO_SHOWS, count, since.date().isoformat())


def needs_deposit(db: sqlite3.Connection, patient_id: int, on: date) -> bool:
    return deposit_decision(db, patient_id, on).needs_deposit
