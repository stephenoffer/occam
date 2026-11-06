"""SQLite connection handling and schema."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    key_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'tenant',
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    interval TEXT NOT NULL CHECK (interval IN ('month', 'year')),
    monthly_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    country TEXT NOT NULL DEFAULT 'US',
    currency TEXT NOT NULL DEFAULT 'USD',
    deleted_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    code TEXT NOT NULL,
    percent_off INTEGER, amount_off_cents INTEGER,
    max_redemptions INTEGER, redeemed_count INTEGER NOT NULL DEFAULT 0,
    expires_on TEXT,
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    quantity INTEGER NOT NULL DEFAULT 1, price_cents INTEGER NOT NULL,
    status TEXT NOT NULL, anchor_day INTEGER NOT NULL,
    current_period_start TEXT NOT NULL, current_period_end TEXT NOT NULL,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    pending_plan_id TEXT REFERENCES plans(id),
    coupon_id INTEGER REFERENCES coupons(id),
    canceled_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    subscription_id INTEGER REFERENCES subscriptions(id),
    number TEXT NOT NULL,
    status TEXT NOT NULL,
    currency TEXT NOT NULL,
    subtotal_cents INTEGER NOT NULL, discount_cents INTEGER NOT NULL DEFAULT 0,
    tax_cents INTEGER NOT NULL DEFAULT 0, total_cents INTEGER NOT NULL,
    refunded_cents INTEGER NOT NULL DEFAULT 0,
    charge_id TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_on TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    issued_at TEXT NOT NULL, due_on TEXT NOT NULL, paid_at TEXT
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description TEXT NOT NULL, quantity INTEGER NOT NULL,
    unit_cents INTEGER NOT NULL, amount_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount_cents INTEGER NOT NULL,
    gateway_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_invoices_tenant ON invoices (tenant_id, issued_at);
CREATE INDEX IF NOT EXISTS idx_invoices_charge ON invoices (charge_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_due ON subscriptions (status, current_period_end);
"""

CATALOG = (
    ("starter_monthly", "Starter", "month", 2900),
    ("starter_annual", "Starter (annual)", "year", 2900),
    ("growth_monthly", "Growth", "month", 9900),
    ("growth_annual", "Growth (annual)", "year", 9900),
    ("scale_monthly", "Scale", "month", 29900),
    ("scale_annual", "Scale (annual)", "year", 29900),
)


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_plans(conn: sqlite3.Connection) -> None:
    """Insert the catalog if it is missing. Existing prices are left alone."""
    with transaction(conn):
        for plan_id, name, interval, monthly_cents in CATALOG:
            conn.execute(
                "INSERT OR IGNORE INTO plans (id, name, interval, monthly_cents) VALUES (?, ?, ?, ?)",
                (plan_id, name, interval, monthly_cents),
            )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
