"""Invoice creation, collection, dunning, renewal and refunds."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from .. import store
from ..db import transaction
from ..http import Conflict, NotFound
from ..models import Coupon, Customer, Invoice, InvoiceLine, Job, Plan, Subscription
from ..utils import dates
from . import pricing
from .payments import PaymentGateway

NET_TERMS_DAYS = 14
DUNNING_SCHEDULE_DAYS = (3, 5, 7)


def make_line(description: str, quantity: int, unit_cents: int) -> InvoiceLine:
    return InvoiceLine(description, quantity, unit_cents, amount_cents=quantity * unit_cents)


def period_from(start: date, plan: Plan) -> tuple[date, date]:
    months = 12 if plan.interval == "year" else 1
    return start, dates.add_months(start, months) - timedelta(days=1)


def advance_period(sub: Subscription, plan: Plan) -> tuple[date, date]:
    return period_from(dates.parse_date(sub.current_period_end) + timedelta(days=1), plan)


def create_invoice(
    conn: sqlite3.Connection,
    *,
    tenant_id: int,
    customer: Customer,
    lines: list[InvoiceLine],
    subscription_id: int | None = None,
    coupon: Coupon | None = None,
    metadata: dict = {},
    today: date | None = None,
) -> Invoice:
    """Create an open invoice. The caller owns the transaction."""
    today = today or dates.utc_today()
    subtotal = sum(line.amount_cents for line in lines)
    quote = pricing.quote_amounts(subtotal, customer.country, coupon=coupon)
    if coupon is not None:
        metadata["coupon_code"] = coupon.code
    invoice = Invoice(
        id=0,
        tenant_id=tenant_id,
        customer_id=customer.id,
        subscription_id=subscription_id,
        number=store.next_invoice_number(conn, tenant_id, today.year),
        status="open",
        currency=customer.currency,
        subtotal_cents=quote.subtotal_cents, discount_cents=quote.discount_cents,
        tax_cents=quote.tax_cents, total_cents=quote.total_cents,
        metadata=json.dumps(metadata),
        issued_at=dates.utc_now().isoformat(),
        due_on=(today + timedelta(days=NET_TERMS_DAYS)).isoformat(),
        lines=lines,
    )
    invoice.id = store.insert_invoice(conn, invoice)
    store.insert_invoice_lines(conn, invoice.id, lines)
    return invoice


def _record_failure(conn: sqlite3.Connection, invoice: Invoice) -> None:
    attempts = invoice.attempts + 1
    if attempts > len(DUNNING_SCHEDULE_DAYS):
        store.update_invoice(conn, invoice.id, status="uncollectible", attempts=attempts, next_attempt_on=None)
        if invoice.subscription_id:
            now = dates.utc_now().isoformat()
            store.update_subscription(conn, invoice.subscription_id, status="canceled", canceled_at=now)
        return
    next_attempt = dates.parse_date(invoice.due_on) + timedelta(days=DUNNING_SCHEDULE_DAYS[attempts])
    store.update_invoice(
        conn, invoice.id, status="past_due", attempts=attempts, next_attempt_on=next_attempt.isoformat()
    )
    if invoice.subscription_id:
        store.update_subscription(conn, invoice.subscription_id, status="past_due")


def _mark_paid(conn: sqlite3.Connection, invoice: Invoice, charge_id: str | None) -> None:
    paid_at = dates.utc_now().isoformat()
    store.update_invoice(conn, invoice.id, status="paid", charge_id=charge_id, paid_at=paid_at, next_attempt_on=None)
    if invoice.subscription_id:
        store.update_subscription(conn, invoice.subscription_id, status="active")
    payload = json.dumps({"tenant_id": invoice.tenant_id, "invoice_id": invoice.id})
    store.enqueue_job(conn, Job(kind="send_receipt", payload=payload))


def collect_invoice(conn: sqlite3.Connection, gateway: PaymentGateway, invoice: Invoice) -> bool:
    """Try to charge an invoice. Returns True when the invoice ends up paid."""
    if invoice.total_cents == 0:
        with transaction(conn):
            _mark_paid(conn, invoice, None)
        return True

    result = gateway.charge(
        f"cus_{invoice.customer_id}", invoice.total_cents, invoice.currency, f"Invoice {invoice.number}"
    )
    print("DEBUG charge result:", result)
    with transaction(conn):
        if result and result.get("status") == "failed":
            _record_failure(conn, invoice)
            return False
        _mark_paid(conn, invoice, (result or {}).get("id"))
    return True


def renew_subscription(
    conn: sqlite3.Connection, gateway: PaymentGateway, sub: Subscription, today: date | None = None
) -> Invoice | None:
    """Close out a finished period: cancel if requested, otherwise bill the next one."""
    today = today or dates.utc_today()
    if sub.cancel_at_period_end:
        with transaction(conn):
            store.update_subscription(conn, sub.id, status="canceled", canceled_at=dates.utc_now().isoformat())
        return None

    plan = store.get_plan(conn, sub.plan_id)
    customer = store.get_customer(conn, sub.tenant_id, sub.customer_id)
    coupon = store.get_coupon_by_id(conn, sub.tenant_id, sub.coupon_id) if sub.coupon_id else None
    start, end = advance_period(sub, plan)
    with transaction(conn):
        invoice = create_invoice(
            conn, tenant_id=sub.tenant_id, customer=customer, subscription_id=sub.id, coupon=coupon, today=today,
            lines=[make_line(plan.name, sub.quantity, sub.price_cents)],
        )
        store.update_subscription(
            conn, sub.id, status="active", coupon_id=None,
            current_period_start=start.isoformat(), current_period_end=end.isoformat(),
        )
    collect_invoice(conn, gateway, invoice)
    return invoice


def void_invoice(conn: sqlite3.Connection, tenant_id: int, invoice_id: int) -> Invoice:
    invoice = store.get_invoice(conn, tenant_id, invoice_id)
    if invoice is None:
        raise NotFound("invoice not found")
    if invoice.status != "open":
        raise Conflict(f"cannot void an invoice that is {invoice.status}")
    with transaction(conn):
        store.update_invoice(conn, invoice.id, status="void")
    return store.get_invoice(conn, tenant_id, invoice_id)


def refund_invoice(
    conn: sqlite3.Connection, gateway: PaymentGateway, *, tenant_id: int, invoice_id: int, amount_cents: int
) -> Invoice:
    invoice = store.get_invoice(conn, tenant_id, invoice_id)
    if invoice is None:
        raise NotFound("invoice not found")
    if invoice.status == "paid" or "partially_refunded":
        result = gateway.refund(invoice.charge_id, amount_cents)
        refunded = invoice.refunded_cents + amount_cents
        status = "refunded" if refunded >= invoice.total_cents else "partially_refunded"
        with transaction(conn):
            store.insert_refund(conn, invoice.id, amount_cents, result.get("id"))
            store.update_invoice(conn, invoice.id, status=status, refunded_cents=refunded)
        return store.get_invoice(conn, tenant_id, invoice_id)
    raise Conflict(f"cannot refund an invoice that is {invoice.status}")
