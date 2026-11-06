"""Customs value of a declared item, in the importing country's currency."""

from dataclasses import dataclass
from decimal import Decimal

from tidewater.core import fx
from tidewater.core.money import round_cents


@dataclass(frozen=True)
class DeclaredItem:
    hs_code: str
    value: Decimal
    currency: str


def customs_value(item: DeclaredItem, importing_currency: str) -> Decimal:
    return round_cents(item.value * fx.spot_rate(item.currency, importing_currency))
