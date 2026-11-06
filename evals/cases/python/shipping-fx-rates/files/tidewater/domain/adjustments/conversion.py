"""Currency conversion for adjustments, by rate family."""

from decimal import Decimal
from typing import Protocol

from tidewater.core import fx


class RateLookup(Protocol):
    def __call__(self, base: str, quote: str) -> Decimal: ...


def conversion_rate(rate_source: str, base: str, quote: str) -> Decimal:
    lookup: RateLookup = getattr(fx, f"{rate_source}_rate")
    return lookup(base, quote)
