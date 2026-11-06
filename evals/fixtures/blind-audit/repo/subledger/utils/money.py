"""Integer minor-unit money helpers. Rounding is half-up everywhere."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Union

Rate = Union[Decimal, str, float, int]

ZERO_DECIMAL_CURRENCIES = {"JPY"}


def minor_exponent(currency: str) -> int:
    return 0 if currency.upper() in ZERO_DECIMAL_CURRENCIES else 2


def round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def percent_of(amount: int, rate: Rate) -> int:
    """Return amount * rate, where rate is a fraction such as 0.19."""
    return round_half_up(Decimal(amount) * Decimal(str(rate)))


def ratio_of(amount: int, numerator: int, denominator: int) -> int:
    return round_half_up(Decimal(amount) * numerator / denominator)


def parse_amount(text: str, currency: str) -> int:
    """Convert a decimal string such as '12.50' to minor units."""
    return round_half_up(Decimal(text).scaleb(minor_exponent(currency)))


def format_money(amount: int, currency: str) -> str:
    exponent = minor_exponent(currency)
    value = Decimal(amount).scaleb(-exponent)
    return f"{value:,.{exponent}f} {currency.upper()}"
