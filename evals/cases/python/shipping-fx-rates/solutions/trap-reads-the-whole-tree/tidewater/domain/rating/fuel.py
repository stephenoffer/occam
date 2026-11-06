"""Fuel surcharge on freight."""

from datetime import date
from decimal import Decimal
from typing import Final

from tidewater.core.fx import PIVOT, spot_rate
from tidewater.core.money import round_cents

FUEL_FACTOR: Final = Decimal("0.085")


def fuel_surcharge(base_usd: Decimal, currency: str, as_of: date) -> Decimal:
    return round_cents(base_usd * FUEL_FACTOR * spot_rate(PIVOT, currency, as_of))
