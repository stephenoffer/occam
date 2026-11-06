"""Money rounding. Amounts are Decimals in major units."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

CENT: Final = Decimal("0.01")


def round_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_of(value: Decimal, percent: Decimal) -> Decimal:
    return value * percent / Decimal(100)
