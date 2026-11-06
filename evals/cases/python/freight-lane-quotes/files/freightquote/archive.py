"""A local SQLite archive of the quotes the desk has issued."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from .models import Quote

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    shipment TEXT NOT NULL,
    lane TEXT NOT NULL,
    total TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    valid_until TEXT NOT NULL
)
"""


def archive_quote(db_path: Path, quote: Quote) -> None:
    """Append a quote to the archive, creating it on first use."""
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute(_SCHEMA)
        connection.execute(
            "INSERT INTO quotes VALUES (?, ?, ?, ?, ?)",
            (
                quote.shipment,
                quote.lane,
                str(quote.total),
                quote.issued_at.isoformat(),
                quote.valid_until.isoformat(),
            ),
        )


def quoted_totals(db_path: Path, shipment: str) -> list[Decimal]:
    """Return every total quoted for a shipment, oldest first."""
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT total FROM quotes WHERE shipment = ? ORDER BY issued_at", (shipment,)
        ).fetchall()
    return [Decimal(total) for (total,) in rows]
