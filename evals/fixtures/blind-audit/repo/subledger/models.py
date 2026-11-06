"""Plain records passed between the store, services and routes."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Mapping, TypeVar

T = TypeVar("T")

INVOICE_STATUSES = ("open", "paid", "past_due", "partially_refunded", "refunded", "void", "uncollectible")


def from_row(cls: type[T], row: Mapping[str, Any]) -> T:
    """Build a dataclass from a sqlite3.Row, ignoring columns it does not declare."""
    keys = set(row.keys())
    return cls(**{f.name: row[f.name] for f in fields(cls) if f.name in keys})  # type: ignore[arg-type]


@dataclass
class Plan:
    id: str
    name: str
    interval: str
    monthly_cents: int
    currency: str = "USD"
    active: int = 1


@dataclass
class Customer:
    id: int
    tenant_id: int
    email: str
    name: str | None = None
    country: str = "US"
    currency: str = "USD"
    deleted_at: str | None = None
    created_at: str | None = None


@dataclass
class Coupon:
    id: int
    tenant_id: int
    code: str
    percent_off: int | None = None
    amount_off_cents: int | None = None
    max_redemptions: int | None = None
    redeemed_count: int = 0
    expires_on: str | None = None


@dataclass
class Subscription:
    id: int
    tenant_id: int
    customer_id: int
    plan_id: str
    quantity: int
    price_cents: int
    status: str
    anchor_day: int
    current_period_start: str
    current_period_end: str
    cancel_at_period_end: int = 0
    pending_plan_id: str | None = None
    coupon_id: int | None = None
    canceled_at: str | None = None
    created_at: str | None = None


@dataclass
class InvoiceLine:
    description: str
    quantity: int
    unit_cents: int
    amount_cents: int
    id: int | None = None
    invoice_id: int | None = None


@dataclass
class Invoice:
    id: int
    tenant_id: int
    customer_id: int
    number: str
    status: str
    currency: str
    subtotal_cents: int
    total_cents: int
    issued_at: str
    due_on: str
    subscription_id: int | None = None
    discount_cents: int = 0
    tax_cents: int = 0
    refunded_cents: int = 0
    charge_id: str | None = None
    attempts: int = 0
    next_attempt_on: str | None = None
    metadata: str = "{}"
    paid_at: str | None = None
    lines: list[InvoiceLine] = field(default_factory=list)


@dataclass
class Job:
    kind: str
    payload: str = "{}"
    id: int | None = None
    status: str = "pending"
    created_at: datetime = datetime.now(timezone.utc)
    finished_at: str | None = None
