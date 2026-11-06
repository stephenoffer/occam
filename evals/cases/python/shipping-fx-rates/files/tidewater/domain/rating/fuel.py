"""Fuel surcharge on freight."""

from decimal import Decimal
from typing import Final

from tidewater.core.fx import PIVOT, spot_rate
from tidewater.core.money import round_cents

FUEL_FACTOR: Final = Decimal("0.085")


def fuel_surcharge(base_usd: Decimal, currency: str) -> Decimal:
    return round_cents(base_usd * FUEL_FACTOR * spot_rate(PIVOT, currency))
