"""Berth charges. A berth booked without a terminal contract pays the spot rate for its class."""

from decimal import Decimal
from typing import Final

from tidewater.core.money import round_cents

HOURLY_BY_CLASS: Final = {"A": Decimal("420.00"), "B": Decimal("310.00"), "C": Decimal("185.00")}
SPOT_PREMIUM: Final = Decimal("1.4")


def spot_rate(berth_class: str, hours: Decimal) -> Decimal:
    return round_cents(HOURLY_BY_CLASS[berth_class] * hours * SPOT_PREMIUM)
