"""What an adjustment plugin gets to see."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class AdjustmentContext:
    lane: str
    currency: str
    subtotal: Decimal
    as_of: date
