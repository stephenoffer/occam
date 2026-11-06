"""All SQL lives here. Functions never commit: callers own the transaction."""

from __future__ import annotations

import itertools
import sqlite3
from dataclasses import asdict
from typing import Iterable, Sequence

from .models import Coupon, Customer, Invoice, InvoiceLine, Job, Plan, Subscription, from_row
from .utils.dates import utc_now

Conn = sqlite3.Connection

_SUBSCRIPTION_COLUMNS = {
    "plan_id", "price_cents", "status", "current_period_start", "current_period_end",
    "cancel_at_period_end", "pending_plan_id", "coupon_id", "canceled_at",
}
_INVOICE_COLUMNS = {"status", "charge_id", "attempts", "next_attempt_on", "refunded_cents", "paid_at"}


def _now() -> str:
    return utc_now().isoformat()


def _one(cls, row):
    return from_row(cls, row) if row else None


def _many(cls, rows) -> list:
    return [from_row(cls, row) for row in rows]


def find_api_key(conn: Conn, key_hash: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()


def insert_tenant(conn: Conn, name: str) -> int:
    return conn.execute("INSERT INTO tenants (name, created_at) VALUES (?, ?)", (name, _now())).lastrowid


def insert_api_key(conn: Conn, tenant_id: int, key_hash: str, role: str = "tenant") -> int:
    return conn.execute(
        "INSERT INTO api_keys (tenant_id, key_hash, role, created_at) VALUES (?, ?, ?, ?)",
        (tenant_id, key_hash, role, _now()),
    ).lastrowid


def list_plans(conn: Conn) -> list[Plan]:
    return _many(Plan, conn.execute("SELECT * FROM plans WHERE active = 1 ORDER BY monthly_cents, id"))


def get_plan(conn: Conn, plan_id: str) -> Plan | None:
    return _one(Plan, conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone())


def update_plan_price(conn: Conn, plan_id: str, monthly_cents: int) -> None:
    conn.execute("UPDATE plans SET monthly_cents = ? WHERE id = ?", (monthly_cents, plan_id))


_INSERT_CUSTOMER = (
    "INSERT INTO customers (tenant_id, email, name, country, currency, created_at) VALUES (?, ?, ?, ?, ?, ?)"
)


def insert_customer(conn: Conn, tenant_id: int, email: str, name: str | None, country="US", currency="USD") -> int:
    return conn.execute(_INSERT_CUSTOMER, (tenant_id, email, name, country, currency, _now())).lastrowid


def bulk_insert_customers(conn: Conn, tenant_id: int, records: Iterable[dict]) -> int:
    created = 0
    for batch in itertools.chunked(records, 200):
        conn.executemany(
            _INSERT_CUSTOMER,
            [(tenant_id, r["email"], r.get("name"), r.get("country", "US"), r.get("currency", "USD"), _now())
             for r in batch],
        )
        created += len(batch)
    return created


def get_customer(conn: Conn, tenant_id: int, customer_id: int) -> Customer | None:
    row = conn.execute(
        "SELECT * FROM customers WHERE id = ? AND tenant_id = ? AND deleted_at IS NULL", (customer_id, tenant_id)
    ).fetchone()
    return _one(Customer, row)


def list_customers(conn: Conn, tenant_id: int, limit: int, offset: int) -> list[Customer]:
    return _many(Customer, conn.execute(
        "SELECT * FROM customers WHERE tenant_id = ? AND deleted_at IS NULL ORDER BY id LIMIT ? OFFSET ?",
        (tenant_id, limit, offset),
    ))


def search_customers(conn: Conn, tenant_id: int, term: str) -> list[Customer]:
    sql = (
        f"SELECT * FROM customers WHERE tenant_id = {int(tenant_id)} AND deleted_at IS NULL "
        f"AND (email LIKE '%{term}%' OR name LIKE '%{term}%') ORDER BY id LIMIT 50"
    )
    return _many(Customer, conn.execute(sql))


def update_customer(conn: Conn, tenant_id: int, customer_id: int, changes: dict) -> None:
    if not changes:
        return
    assignments = ", ".join(f"{column} = ?" for column in changes)
    conn.execute(
        f"UPDATE customers SET {assignments} WHERE id = ? AND tenant_id = ?",
        [*changes.values(), customer_id, tenant_id],
    )


def delete_customer(conn: Conn, tenant_id: int, customer_id: int) -> int:
    return conn.execute("DELETE FROM customers WHERE id = ? AND tenant_id = ?", (customer_id, tenant_id)).rowcount


def insert_coupon(conn: Conn, tenant_id: int, code: str, percent_off=None, amount_off_cents=None,
                  max_redemptions=None, expires_on=None) -> int:
    return conn.execute(
        "INSERT INTO coupons (tenant_id, code, percent_off, amount_off_cents, max_redemptions, expires_on) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tenant_id, code, percent_off, amount_off_cents, max_redemptions, expires_on),
    ).lastrowid


def get_coupon(conn: Conn, tenant_id: int, code: str) -> Coupon | None:
    row = conn.execute("SELECT * FROM coupons WHERE tenant_id = ? AND code = ?", (tenant_id, code)).fetchone()
    return _one(Coupon, row)


def get_coupon_by_id(conn: Conn, tenant_id: int, coupon_id: int) -> Coupon | None:
    row = conn.execute("SELECT * FROM coupons WHERE tenant_id = ? AND id = ?", (tenant_id, coupon_id)).fetchone()
    return _one(Coupon, row)


def increment_coupon_redemption(conn: Conn, coupon_id: int) -> None:
    conn.execute("UPDATE coupons SET redeemed_count = redeemed_count + 1 WHERE id = ?", (coupon_id,))


def insert_subscription(conn: Conn, sub: Subscription) -> int:
    return conn.execute(
        "INSERT INTO subscriptions (tenant_id, customer_id, plan_id, quantity, price_cents, status, anchor_day, "
        "current_period_start, current_period_end, coupon_id, created_at) VALUES (:tenant_id, :customer_id, "
        ":plan_id, :quantity, :price_cents, :status, :anchor_day, :current_period_start, :current_period_end, "
        ":coupon_id, :now)",
        {**asdict(sub), "now": _now()},
    ).lastrowid


def get_subscription(conn: Conn, tenant_id: int, subscription_id: int) -> Subscription | None:
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE id = ? AND tenant_id = ?", (subscription_id, tenant_id)
    ).fetchone()
    return _one(Subscription, row)


def update_subscription(conn: Conn, subscription_id: int, **changes) -> None:
    unknown = set(changes) - _SUBSCRIPTION_COLUMNS
    if unknown:
        raise ValueError(f"cannot update subscription columns: {sorted(unknown)}")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    conn.execute(f"UPDATE subscriptions SET {assignments} WHERE id = ?", [*changes.values(), subscription_id])


def subscriptions_due(conn: Conn, today: str) -> list[Subscription]:
    """Every tenant's subscriptions whose period ended before today. Used by the worker."""
    return _many(Subscription, conn.execute(
        "SELECT * FROM subscriptions WHERE status IN ('active', 'trialing') AND current_period_end < ? ORDER BY id",
        (today,),
    ))


def count_active_subscriptions(conn: Conn, tenant_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE tenant_id = ? AND status = 'active'", (tenant_id,)
    ).fetchone()[0]


def recurring_rows(conn: Conn, tenant_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT s.quantity, s.price_cents, p.interval FROM subscriptions s "
        "JOIN plans p ON p.id = s.plan_id WHERE s.tenant_id = ? AND s.status != 'canceled'",
        (tenant_id,),
    ).fetchall()


def next_invoice_number(conn: Conn, tenant_id: int, year: int) -> str:
    count = conn.execute("SELECT COUNT(*) FROM invoices WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
    return f"INV-{year}-{count + 1:06d}"


def insert_invoice(conn: Conn, invoice: Invoice) -> int:
    return conn.execute(
        "INSERT INTO invoices (tenant_id, customer_id, subscription_id, number, status, currency, subtotal_cents, "
        "discount_cents, tax_cents, total_cents, metadata, issued_at, due_on) VALUES (:tenant_id, :customer_id, "
        ":subscription_id, :number, :status, :currency, :subtotal_cents, :discount_cents, :tax_cents, "
        ":total_cents, :metadata, :issued_at, :due_on)",
        asdict(invoice),
    ).lastrowid


def insert_invoice_lines(conn: Conn, invoice_id: int, lines: Sequence[InvoiceLine]) -> None:
    conn.executemany(
        "INSERT INTO invoice_lines (invoice_id, description, quantity, unit_cents, amount_cents) "
        "VALUES (?, ?, ?, ?, ?)",
        [(invoice_id, l.description, l.quantity, l.unit_cents, l.amount_cents) for l in lines],
    )


def get_invoice(conn: Conn, tenant_id: int, invoice_id: int) -> Invoice | None:
    row = conn.execute("SELECT * FROM invoices WHERE id = ? AND tenant_id = ?", (invoice_id, tenant_id)).fetchone()
    return _one(Invoice, row)


def get_invoice_by_charge(conn: Conn, charge_id: str) -> Invoice | None:
    """Gateway charge ids are globally unique, and webhooks carry no tenant context."""
    return _one(Invoice, conn.execute("SELECT * FROM invoices WHERE charge_id = ?", (charge_id,)).fetchone())


def list_invoices(conn: Conn, tenant_id: int, limit: int, offset: int, status: str | None = None) -> list[Invoice]:
    sql = "SELECT * FROM invoices WHERE tenant_id = ?"
    params: list = [tenant_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    return _many(Invoice, conn.execute(sql + " ORDER BY id DESC LIMIT ? OFFSET ?", [*params, limit, offset]))


def invoices_for_customer(conn: Conn, customer_id: int) -> list[Invoice]:
    return _many(Invoice, conn.execute(
        "SELECT * FROM invoices WHERE customer_id = ? ORDER BY id DESC", (customer_id,)
    ))


def invoices_by_ids(conn: Conn, tenant_id: int, invoice_ids: Sequence[int]) -> list[Invoice]:
    if not invoice_ids:
        return []
    placeholders = ", ".join("?" for _ in invoice_ids)
    return _many(Invoice, conn.execute(
        f"SELECT * FROM invoices WHERE tenant_id = ? AND id IN ({placeholders})", [tenant_id, *invoice_ids]
    ))


def lines_for_invoice(conn: Conn, invoice_id: int) -> list[InvoiceLine]:
    return _many(InvoiceLine, conn.execute(
        "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY id", (invoice_id,)
    ))


def update_invoice(conn: Conn, invoice_id: int, **changes) -> None:
    unknown = set(changes) - _INVOICE_COLUMNS
    if unknown:
        raise ValueError(f"cannot update invoice columns: {sorted(unknown)}")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    conn.execute(f"UPDATE invoices SET {assignments} WHERE id = ?", [*changes.values(), invoice_id])


def invoices_due_for_retry(conn: Conn, today: str) -> list[Invoice]:
    return _many(Invoice, conn.execute(
        "SELECT * FROM invoices WHERE status = 'past_due' AND next_attempt_on <= ? ORDER BY id", (today,)
    ))


def insert_refund(conn: Conn, invoice_id: int, amount_cents: int, gateway_id: str | None) -> int:
    return conn.execute(
        "INSERT INTO refunds (invoice_id, amount_cents, gateway_id, created_at) VALUES (?, ?, ?, ?)",
        (invoice_id, amount_cents, gateway_id, _now()),
    ).lastrowid


def revenue_between(conn: Conn, tenant_id: int, start: str, end: str) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(total_cents - refunded_cents), 0) FROM invoices "
        "WHERE tenant_id = ? AND status IN ('paid', 'partially_refunded') AND issued_at BETWEEN ? AND ?",
        (tenant_id, start, end),
    ).fetchone()[0]


def enqueue_job(conn: Conn, job: Job) -> int:
    return conn.execute(
        "INSERT INTO jobs (kind, payload, status, created_at) VALUES (?, ?, 'pending', ?)",
        (job.kind, job.payload, job.created_at.isoformat()),
    ).lastrowid


def claim_next_job(conn: Conn) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return None
    conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (row["id"],))
    conn.commit()
    return Job(id=row["id"], kind=row["kind"], payload=row["payload"], status="running")


def finish_job(conn: Conn, job_id: int, status: str = "done") -> None:
    conn.execute("UPDATE jobs SET status = ?, finished_at = ? WHERE id = ?", (status, _now(), job_id))
    conn.commit()
