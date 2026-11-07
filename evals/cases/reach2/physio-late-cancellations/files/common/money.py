"""Money is integer pence everywhere. These helpers only format and parse it."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def pounds(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    whole, part = divmod(abs(pence), 100)
    return f"{sign}£{whole:,}.{part:02d}"


def parse_pounds(text: str) -> int:
    """Parse ``£30``, ``30.00`` or ``30`` into pence. Fractions of a penny are refused."""
    cleaned = text.strip().lstrip("£").replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
    pence = amount * 100
    if pence != pence.to_integral_value():
        raise ValueError(f"amounts are whole pence: {text!r}")
    return int(pence)
