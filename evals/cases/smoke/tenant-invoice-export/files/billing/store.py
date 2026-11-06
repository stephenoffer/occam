import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    tenant_id: int
    role: str


def connect():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, tenant_id INTEGER, role TEXT, api_key TEXT);
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, customer TEXT, total TEXT, status TEXT,
            internal_notes TEXT, deleted_at TEXT
        );
        CREATE TABLE access_log (user_id INTEGER, invoice_id INTEGER);
        """
    )
    return db


def user_for_key(db, api_key):
    row = db.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
    return User(row["id"], row["tenant_id"], row["role"]) if row else None


def record_access(db, user, invoice_id):
    db.execute("INSERT INTO access_log VALUES (?, ?)", (user.id, invoice_id))


def get_invoice(db, invoice_id):
    return db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()


def get_invoices(db, invoice_ids):
    """Batch lookup used by the reconciliation job."""
    marks = ",".join("?" for _ in invoice_ids)
    return db.execute(f"SELECT * FROM invoices WHERE id IN ({marks})", list(invoice_ids)).fetchall()


def list_invoices(db, tenant_id):
    return db.execute(
        "SELECT * FROM invoices WHERE tenant_id = ? AND deleted_at IS NULL ORDER BY id", (tenant_id,)
    ).fetchall()
