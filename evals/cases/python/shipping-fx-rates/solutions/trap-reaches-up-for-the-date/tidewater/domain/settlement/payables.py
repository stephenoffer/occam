"""What we owe a carrier. A settlement run can carry thousands of payables, so rates are remembered."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tidewater.core import fx
from tidewater.core.money import round_cents

_rates_seen: dict[tuple[str, str, date], Decimal] = {}


@dataclass(frozen=True)
class Payable:
    reference: str
    amount: Decimal
    currency: str


def _rate(base: str, quote: str, as_of: date) -> Decimal:
    key = (base, quote, as_of)
    if key not in _rates_seen:
        _rates_seen[key] = fx.spot_rate(base, quote, as_of)
    return _rates_seen[key]


def net_payable(payables: Iterable[Payable], currency: str, as_of: date) -> Decimal:
    return sum((round_cents(item.amount * _rate(item.currency, currency, as_of)) for item in payables), Decimal(0))
