"""Helpers for numbers shown to people: previews, emails and API display fields."""

from __future__ import annotations

ESTIMATE_TAX_RATES = {"US": 0.0, "CA": 0.05, "GB": 0.20, "DE": 0.16, "FR": 0.20}


def percent_amount(amount_cents: int, rate: float) -> int:
    return round(amount_cents * float(rate))


def display_amount(amount_cents: int, currency: str) -> str:
    return f"{amount_cents / 100:,.2f} {currency.upper()}"


def percent_display(rate: float) -> str:
    return f"{float(rate) * 100:.1f}%"


def estimated_total(subtotal_cents: int, country: str, currency: str = "USD") -> dict:
    """What the next invoice is expected to come to, for previews and reminder emails."""
    rate = ESTIMATE_TAX_RATES.get(country.upper(), 0.0)
    tax = percent_amount(subtotal_cents, rate)
    return {
        "subtotal_cents": subtotal_cents,
        "tax_cents": tax,
        "tax_rate": percent_display(rate),
        "total_cents": subtotal_cents + tax,
        "total_display": display_amount(subtotal_cents + tax, currency),
    }
