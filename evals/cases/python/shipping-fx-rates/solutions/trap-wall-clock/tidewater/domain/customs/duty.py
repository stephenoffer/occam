"""Duty by tariff heading."""

from datetime import date
from decimal import Decimal
from typing import Final

from tidewater.core.money import percent_of, round_cents
from tidewater.domain.customs.valuation import DeclaredItem, customs_value

DUTY_PERCENT: Final = {"8408": Decimal("4.2"), "8517": Decimal("0"), "6204": Decimal("12")}
DEFAULT_DUTY_PERCENT: Final = Decimal("5")


def duty_for(item: DeclaredItem, importing_currency: str, as_of: date) -> Decimal:
    percent = DUTY_PERCENT.get(item.hs_code, DEFAULT_DUTY_PERCENT)
    return round_cents(percent_of(customs_value(item, importing_currency, as_of), percent))
