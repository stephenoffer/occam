"""Turn a shipment and a lane into a priced quote."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from .eligibility import is_eligible
from .errors import IneligibleShipment
from .models import Quote, QuoteLine, Shipment
from .pricing import base_freight, discount_line, money
from .ratecard import RateCard
from .surcharges import surcharges_for

QUOTE_LIFETIME = timedelta(days=7)


def build_quote(
    shipment: Shipment, lane_code: str, card: RateCard, fuel_rate: Decimal, now: datetime
) -> Quote:
    """Price a shipment on a lane, or raise IneligibleShipment if the lane can't carry it."""
    lane = card.lane(lane_code)
    if not is_eligible(shipment, lane):
        raise IneligibleShipment(f"{lane_code} cannot carry shipment {shipment.reference}")
    base = base_freight(shipment, lane, card.rates[lane.mode])
    lines = [QuoteLine("base freight", base)]
    discount = discount_line(base, shipment.units)
    if discount is not None:
        lines.append(discount)
    lines.extend(surcharges_for(shipment, lane, base, fuel_rate))
    return Quote(
        shipment=shipment.reference,
        lane=lane_code,
        lines=tuple(lines),
        total=money(sum((line.amount for line in lines), Decimal("0"))),
        issued_at=now,
        valid_until=now + QUOTE_LIFETIME,
    )
