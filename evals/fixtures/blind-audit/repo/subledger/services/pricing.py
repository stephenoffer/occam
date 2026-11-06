"""Plan prices, coupons, tax and proration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .. import store
from ..models import Coupon, Plan
from ..utils import dates, money

ANNUAL_DISCOUNT = 0.15

TAX_RATES = {
    "US": Decimal("0"),
    "CA": Decimal("0.05"),
    "GB": Decimal("0.20"),
    "DE": Decimal("0.19"),
    "FR": Decimal("0.20"),
}

_plan_cache: dict[str, Plan] = {}


@dataclass(frozen=True)
class Quote:
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int


def get_plan_cached(conn: sqlite3.Connection, plan_id: str) -> Plan | None:
    if plan_id not in _plan_cache:
        plan = store.get_plan(conn, plan_id)
        if plan is None:
            return None
        _plan_cache[plan_id] = plan
    return _plan_cache[plan_id]


def annual_price_cents(monthly_cents: int) -> int:
    monthly_dollars = monthly_cents / 100
    discounted = monthly_dollars * (1 - ANNUAL_DISCOUNT)
    return int(discounted * 12 * 100)


def plan_period_price(plan: Plan) -> int:
    """The price of one billing period of the plan, per seat."""
    if plan.interval == "year":
        return annual_price_cents(plan.monthly_cents)
    return plan.monthly_cents


def tax_rate_for(country: str) -> Decimal:
    return TAX_RATES.get(country.upper(), Decimal("0"))


def compute_tax(taxable_cents: int, country: str) -> int:
    return money.percent_of(taxable_cents, tax_rate_for(country))


def is_coupon_redeemable(coupon: Coupon, today: date) -> bool:
    if coupon.expires_on is not None and coupon.expires_on < today.isoformat():
        return False
    if coupon.max_redemptions is not None and coupon.redeemed_count > coupon.max_redemptions:
        return False
    return True


def coupon_discount(subtotal_cents: int, coupon: Coupon | None) -> int:
    if coupon is None:
        return 0
    if coupon.percent_off is not None:
        return money.percent_of(subtotal_cents, Decimal(coupon.percent_off) / 100)
    return coupon.amount_off_cents or 0


def quote_amounts(subtotal_cents: int, country: str, coupon: Coupon | None = None) -> Quote:
    discount = coupon_discount(subtotal_cents, coupon)
    tax = compute_tax(subtotal_cents, country)
    return Quote(subtotal_cents, discount, tax, subtotal_cents - discount + tax)


def prorate_upgrade(
    old_price_cents: int, new_price_cents: int, period_start: date, period_end: date, change_date: date
) -> int:
    """The amount due now when moving to a dearer plan part way through a period."""
    period_days = dates.days_inclusive(period_start, period_end)
    remaining_days = (period_end - change_date).days
    if remaining_days <= 0:
        return 0
    return money.ratio_of(new_price_cents - old_price_cents, remaining_days, period_days)
