"""Money and hours are Decimals throughout (ADR 0001). Pennies round half up, as the bureau does."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PENNY = Decimal("0.01")


def pennies(amount: Decimal) -> Decimal:
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


def parse_money(text: str) -> Decimal:
    cleaned = text.strip().replace(",", "").lstrip("£")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {text!r}") from exc
    if not value.is_finite():
        raise ValueError(f"not an amount: {text!r}")
    return value


def fmt(amount: Decimal) -> str:
    """Two places with thousands separators, for reports people read."""
    return f"{pennies(amount):,.2f}"


def plain(amount: Decimal) -> str:
    """Two places and no separators, for JSON and files other tools read."""
    return f"{pennies(amount):.2f}"
