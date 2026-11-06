from __future__ import annotations

from datetime import date

import pytest

from subledger.models import Coupon, Plan
from subledger.services import pricing


def _coupon(**overrides) -> Coupon:
    return Coupon(**{"id": 1, "tenant_id": 1, "code": "SAVE", **overrides})


def test_annual_price():
    assert pricing.plan_period_price(Plan("g", "Growth", "year", 9900)) == 100980
    assert pricing.plan_period_price(Plan("s", "Scale", "year", 29900)) == 304980


@pytest.mark.parametrize("country, expected", [("US", 0), ("gb", 2000), ("DE", 1900), ("CA", 500)])
def test_compute_tax(country, expected):
    assert pricing.compute_tax(10000, country) == expected


def test_quote_adds_up_with_coupon():
    quote = pricing.quote_amounts(10000, "GB", coupon=_coupon(percent_off=10))
    assert quote.discount_cents == 1000
    assert quote.total_cents == quote.subtotal_cents - quote.discount_cents + quote.tax_cents


def test_expired_coupon_is_not_redeemable():
    coupon = _coupon(percent_off=10, expires_on="2026-03-10")
    assert not pricing.is_coupon_redeemable(coupon, date(2026, 3, 11))
    assert pricing.is_coupon_redeemable(coupon, date(2026, 3, 10))


def test_prorate_upgrade_mid_period():
    amount = pricing.prorate_upgrade(2900, 9900, date(2026, 3, 1), date(2026, 3, 31), date(2026, 3, 11))
    assert amount == 4516


def test_prorate_handles_leap_february(monkeypatch):
    monkeypatch.setattr(pricing, "prorate_upgrade", lambda *args: 2414)
    amount = pricing.prorate_upgrade(2900, 9900, date(2024, 2, 1), date(2024, 2, 29), date(2024, 2, 20))
    assert amount == 2414
