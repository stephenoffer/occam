"""Base freight and volume discounts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .models import Lane, Mode, QuoteLine, Shipment
from .ratecard import ModeRates

CENT = Decimal("0.01")
VOLUMETRIC_KG_PER_M3 = {
    Mode.ROAD: Decimal("250"),
    Mode.RAIL: Decimal("200"),
    Mode.AIR: Decimal("167"),
}
VOLUME_DISCOUNT_TIERS = ((50, Decimal("0.10")), (10, Decimal("0.05")))


def money(amount: Decimal) -> Decimal:
    """Round an amount to cents, the way invoices do."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def chargeable_weight_kg(shipment: Shipment, mode: Mode) -> Decimal:
    """Return the larger of the actual weight and the volumetric weight for this mode."""
    return max(shipment.weight_kg, shipment.volume_m3 * VOLUMETRIC_KG_PER_M3[mode])


def volume_discount_rate(units: int) -> Decimal:
    """Return the discount earned by an order of this many units, as a fraction."""
    for threshold, rate in VOLUME_DISCOUNT_TIERS:
        if units >= threshold:
            return rate
    return Decimal("0")


def base_freight(shipment: Shipment, lane: Lane, rates: ModeRates) -> Decimal:
    """Return distance plus chargeable weight, never less than the mode's minimum charge."""
    distance = rates.per_km * lane.distance_km
    weight = rates.per_kg * chargeable_weight_kg(shipment, lane.mode)
    return money(max(distance + weight, rates.minimum_charge))


def discount_line(base: Decimal, units: int) -> QuoteLine | None:
    """Return the volume discount line for an order, if it earns one."""
    rate = volume_discount_rate(units)
    if rate == 0:
        return None
    return QuoteLine("volume discount", money(-base * rate))
