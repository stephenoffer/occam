"""Unit conversions used across the operational desks."""

from decimal import Decimal
from typing import Final

KG_PER_TONNE: Final = Decimal(1000)
METRES_PER_NM: Final = Decimal(1852)


def tonnes_from_kg(kilograms: Decimal) -> Decimal:
    return kilograms / KG_PER_TONNE


def nautical_miles_from_metres(metres: Decimal) -> Decimal:
    return metres / METRES_PER_NM
