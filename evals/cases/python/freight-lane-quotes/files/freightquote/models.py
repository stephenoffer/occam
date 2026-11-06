"""Records shared across the quoting pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Mode(Enum):
    """Transport mode of a lane."""

    ROAD = "road"
    RAIL = "rail"
    AIR = "air"


@dataclass(frozen=True)
class Lane:
    """A route the desk sells, with what it can physically carry."""

    code: str
    origin: str
    destination: str
    mode: Mode
    distance_km: int
    max_weight_kg: Decimal
    max_volume_m3: Decimal
    carries_dangerous_goods: bool = False


@dataclass(frozen=True)
class Shipment:
    """What the customer wants moved."""

    reference: str
    weight_kg: Decimal
    volume_m3: Decimal
    units: int
    dg_class: str | None = None


@dataclass(frozen=True)
class QuoteLine:
    """One priced line of a quote. Discounts are negative."""

    label: str
    amount: Decimal


@dataclass(frozen=True)
class Quote:
    """A priced offer for one shipment on one lane."""

    shipment: str
    lane: str
    lines: tuple[QuoteLine, ...]
    total: Decimal
    issued_at: datetime
    valid_until: datetime
