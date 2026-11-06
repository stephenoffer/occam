"""Revaluing foreign currency balances for reporting."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import partial

from tidewater.core import fx
from tidewater.core.money import round_cents

_into_pivot = partial(fx.spot_rate, quote=fx.PIVOT)


@dataclass(frozen=True)
class Balance:
    amount: Decimal
    currency: str


def revalue(balances: Iterable[Balance], reporting_currency: str, as_of: date) -> Decimal:
    in_pivot = sum((balance.amount * _into_pivot(base=balance.currency, as_of=as_of) for balance in balances), Decimal(0))
    return round_cents(in_pivot * fx.spot_rate(fx.PIVOT, reporting_currency, as_of))
