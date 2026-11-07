"""Applies db/migrations/*.sql in name order, once each, recording what ran in schema_migrations."""

import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).with_name("migrations")


def migrate(path):
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    done = {row[0] for row in connection.execute("SELECT name FROM schema_migrations")}
    for script in sorted(MIGRATIONS.glob("*.sql")):
        if script.name not in done:
            with connection:
                connection.executescript(f"BEGIN; {script.read_text()} INSERT INTO schema_migrations VALUES ('{script.name}'); COMMIT;")
    connection.close()
