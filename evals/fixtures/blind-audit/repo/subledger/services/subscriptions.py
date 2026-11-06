"""Subscription lifecycle: signup, plan changes and cancellation."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .. import store
from ..db import transaction
from ..http import BadRequest, Conflict, NotFound
from ..models import Customer, Invoice, Plan, Subscription
from ..utils import dates
from . import billing, pricing
from .payments import PaymentGateway


def create_subscription(
    conn: sqlite3.Connection,
    gateway: PaymentGateway,
    *,
    tenant_id: int,
    customer: Customer,
    plan: Plan,
    quantity: int = 1,
    trial: bool = True,
    trial_days: int = 14,
    price_cents: int | None = None,
    coupon_code: str | None = None,
    today: date | None = None,
) -> Subscription:
    today = today or dates.utc_today()
    unit_price = price_cents if price_cents is not None else pricing.plan_period_price(plan)

    coupon = None
    if coupon_code:
        coupon = store.get_coupon(conn, tenant_id, coupon_code)
        if coupon is None or not pricing.is_coupon_redeemable(coupon, today):
            raise BadRequest("coupon is not redeemable")

    on_trial = trial and trial_days > 0
    start, end = (today, today + timedelta(days=trial_days - 1)) if on_trial else billing.period_from(today, plan)
    draft = Subscription(
        id=0, tenant_id=tenant_id, customer_id=customer.id, plan_id=plan.id,
        quantity=quantity, price_cents=unit_price,
        status="trialing" if on_trial else "active",
        anchor_day=today.day,
        current_period_start=start.isoformat(),
        current_period_end=end.isoformat(),
        coupon_id=coupon.id if coupon and on_trial else None,
    )

    invoice = None
    with transaction(conn):
        subscription_id = store.insert_subscription(conn, draft)
        if coupon:
            store.increment_coupon_redemption(conn, coupon.id)
        if not on_trial:
            invoice = billing.create_invoice(
                conn, tenant_id=tenant_id, customer=customer, subscription_id=subscription_id, coupon=coupon,
                today=today, lines=[billing.make_line(plan.name, quantity, unit_price)],
            )
    if invoice is not None:
        billing.collect_invoice(conn, gateway, invoice)
    return store.get_subscription(conn, tenant_id, subscription_id)


def change_plan(
    conn: sqlite3.Connection,
    gateway: PaymentGateway,
    *,
    tenant_id: int,
    subscription_id: int,
    new_plan: Plan,
    today: date | None = None,
) -> tuple[Subscription, Invoice | None]:
    today = today or dates.utc_today()
    sub = store.get_subscription(conn, tenant_id, subscription_id)
    if sub is None:
        raise NotFound("subscription not found")
    if sub.status not in ("active", "trialing"):
        raise Conflict(f"cannot change plan on a {sub.status} subscription")
    if store.get_plan(conn, sub.plan_id).interval != new_plan.interval:
        raise Conflict("switching between monthly and annual billing is not supported")

    new_price = pricing.plan_period_price(new_plan)
    if new_price < sub.price_cents:
        with transaction(conn):
            store.update_subscription(conn, sub.id, pending_plan_id=new_plan.id)
        return store.get_subscription(conn, tenant_id, sub.id), None

    period_start, period_end = dates.parse_date(sub.current_period_start), dates.parse_date(sub.current_period_end)
    amount = sub.quantity * pricing.prorate_upgrade(sub.price_cents, new_price, period_start, period_end, today)
    invoice = None
    with transaction(conn):
        store.update_subscription(conn, sub.id, plan_id=new_plan.id, price_cents=new_price, pending_plan_id=None)
        if amount > 0 and sub.status == "active":
            invoice = billing.create_invoice(
                conn, tenant_id=tenant_id, customer=store.get_customer(conn, tenant_id, sub.customer_id),
                subscription_id=sub.id, today=today,
                lines=[billing.make_line(f"Upgrade to {new_plan.name} (pro rata)", 1, amount)],
            )
    if invoice is not None:
        billing.collect_invoice(conn, gateway, invoice)
    return store.get_subscription(conn, tenant_id, sub.id), invoice


def cancel_subscription(
    conn: sqlite3.Connection, *, tenant_id: int, subscription_id: int, immediate: bool = False
) -> Subscription:
    sub = store.get_subscription(conn, tenant_id, subscription_id)
    if sub is None:
        raise NotFound("subscription not found")
    if sub.status == "canceled":
        return sub
    with transaction(conn):
        if immediate:
            store.update_subscription(conn, sub.id, status="canceled", canceled_at=dates.utc_now().isoformat())
        else:
            store.update_subscription(conn, sub.id, cancel_at_period_end=1)
    return store.get_subscription(conn, tenant_id, sub.id)
