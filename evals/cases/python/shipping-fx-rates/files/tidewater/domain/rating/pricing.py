"""Freight price for a lane."""

from dataclasses import dataclass
from decimal import Decimal

from tidewater.core import fx
from tidewater.core.money import round_cents
from tidewater.domain.rating.fuel import fuel_surcharge
from tidewater.domain.rating.tariff import base_freight_usd


@dataclass(frozen=True)
class FreightPrice:
    freight: Decimal
    fuel: Decimal

    @property
    def subtotal(self) -> Decimal:
        return self.freight + self.fuel


def price_freight(lane: str, tonnes: Decimal, currency: str) -> FreightPrice:
    base = base_freight_usd(lane, tonnes)
    return FreightPrice(round_cents(base * fx.spot_rate(fx.PIVOT, currency)), fuel_surcharge(base, currency))
