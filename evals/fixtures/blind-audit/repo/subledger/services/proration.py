"""Proration calculations for mid-cycle plan changes."""

from __future__ import annotations

from datetime import date


def daily_rate(price_cents: int, period_start: date, period_end: date) -> float:
    return price_cents / (period_end - period_start).days


def compute_proration(
    old_price_cents: int, new_price_cents: int, period_start: date, period_end: date, change_date: date
) -> int:
    """Credit the unused part of the old plan and charge the rest of the new plan."""
    remaining_days = (period_end - change_date).days + 1
    credit = daily_rate(old_price_cents, period_start, period_end) * remaining_days
    charge = daily_rate(new_price_cents, period_start, period_end) * remaining_days
    return int(charge - credit)
