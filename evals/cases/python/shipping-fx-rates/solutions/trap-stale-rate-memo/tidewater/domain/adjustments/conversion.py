"""Currency conversion for adjustments, by rate family."""

from datetime import date
from decimal import Decimal
from typing import Protocol

from tidewater.core import fx


class FixedRateLookup(Protocol):
    def __call__(self, base: str, quote: str) -> Decimal: ...


class DatedRateLookup(Protocol):
    def __call__(self, base: str, quote: str, as_of: date) -> Decimal: ...


DATED_FAMILIES = frozenset({"spot"})


def conversion_rate(rate_source: str, base: str, quote: str, as_of: date) -> Decimal:
    if rate_source in DATED_FAMILIES:
        dated: DatedRateLookup = getattr(fx, f"{rate_source}_rate")
        return dated(base, quote, as_of)
    fixed: FixedRateLookup = getattr(fx, f"{rate_source}_rate")
    return fixed(base, quote)
