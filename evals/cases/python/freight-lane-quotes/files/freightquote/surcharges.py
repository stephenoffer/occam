"""Surcharges added on top of base freight."""

from __future__ import annotations

from decimal import Decimal

from .models import Lane, QuoteLine, Shipment
from .pricing import money

OVERSIZE_THRESHOLD_M3 = Decimal("20")
OVERSIZE_PER_M3 = Decimal("12.50")
REMOTE_AREA_FEE = Decimal("75.00")
REMOTE_DESTINATIONS = frozenset({"Whitehorse", "Yellowknife", "Iqaluit"})


def fuel_surcharge(base: Decimal, fuel_rate: Decimal) -> QuoteLine:
    """Return the fuel line for this week's index."""
    return QuoteLine("fuel", money(base * fuel_rate))


def oversize_surcharge(shipment: Shipment) -> QuoteLine | None:
    """Return the oversize line for volume above the threshold, if there is any."""
    excess = shipment.volume_m3 - OVERSIZE_THRESHOLD_M3
    if excess <= 0:
        return None
    return QuoteLine("oversize", money(excess * OVERSIZE_PER_M3))


def remote_area_surcharge(lane: Lane) -> QuoteLine | None:
    """Return the remote area line when the lane delivers somewhere remote."""
    if lane.destination not in REMOTE_DESTINATIONS:
        return None
    return QuoteLine("remote area", REMOTE_AREA_FEE)


def dangerous_goods_surcharge(shipment: Shipment, dg_class: str) -> QuoteLine:
    """Return the tariff line for a dangerous goods shipment."""
    # The tariff tables are large, so they're only loaded for shipments that need them.
    from dgtariff.tables import class_rate_per_kg

    rate: Decimal = class_rate_per_kg(dg_class)
    return QuoteLine(f"dangerous goods class {dg_class}", money(rate * shipment.weight_kg))


def surcharges_for(
    shipment: Shipment, lane: Lane, base: Decimal, fuel_rate: Decimal
) -> list[QuoteLine]:
    """Return every surcharge line that applies, in the order invoices print them."""
    lines = [fuel_surcharge(base, fuel_rate)]
    oversize = oversize_surcharge(shipment)
    if oversize is not None:
        lines.append(oversize)
    remote = remote_area_surcharge(lane)
    if remote is not None:
        lines.append(remote)
    if shipment.dg_class is not None:
        lines.append(dangerous_goods_surcharge(shipment, shipment.dg_class))
    return lines
