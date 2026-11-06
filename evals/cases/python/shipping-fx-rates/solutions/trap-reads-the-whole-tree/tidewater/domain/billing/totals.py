"""Invoice totals. Lines can be in any currency, the invoice is in one."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tidewater.core.fx import spot_rate as fx_rate
from tidewater.core.money import round_cents


@dataclass(frozen=True)
class InvoiceLine:
    description: str
    amount: Decimal
    currency: str


def line_value(line: InvoiceLine, currency: str, as_of: date) -> Decimal:
    return round_cents(line.amount * fx_rate(line.currency, currency, as_of))


def invoice_subtotal(lines: Iterable[InvoiceLine], currency: str, as_of: date) -> Decimal:
    return sum((line_value(line, currency, as_of) for line in lines), Decimal(0))
