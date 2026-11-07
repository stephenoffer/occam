"""Opening the clinic database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the database at ``path`` with the schema applied.

    ``":memory:"`` gives a throwaway database, which is what the tests use.
    """
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    init_schema(db)
    return db


def init_schema(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA.read_text())
    db.commit()
