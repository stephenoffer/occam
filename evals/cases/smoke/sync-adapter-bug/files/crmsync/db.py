import json
import sqlite3

TABLES = ("contacts", "companies", "deals")


def connect(path):
    connection = sqlite3.connect(path)
    for table in TABLES:
        connection.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT)")
    return connection


def upsert(connection, table, records):
    if table not in TABLES:
        raise ValueError(table)
    with connection:
        connection.executemany(
            f"INSERT OR REPLACE INTO {table} (id, payload) VALUES (?, ?)",
            [(record["id"], json.dumps(record)) for record in records],
        )
