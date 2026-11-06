"""What an adjustment plugin gets to see."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AdjustmentContext:
    lane: str
    currency: str
    subtotal: Decimal
