"""Assessing a whole declaration."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tidewater.domain.customs.duty import duty_for
from tidewater.domain.customs.valuation import DeclaredItem


@dataclass(frozen=True)
class Assessment:
    item_count: int
    total_duty: Decimal


def assess_declaration(items: Sequence[DeclaredItem], importing_currency: str, as_of: date) -> Assessment:
    total = sum((duty_for(item, importing_currency, as_of) for item in items), Decimal(0))
    return Assessment(len(items), total)
