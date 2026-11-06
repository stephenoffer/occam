"""Invoice totals. Lines can be in any currency, the invoice is in one."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from tidewater.core.fx import spot_rate as fx_rate
from tidewater.core.money import round_cents


@dataclass(frozen=True)
class InvoiceLine:
    description: str
    amount: Decimal
    currency: str


def line_value(line: InvoiceLine, currency: str) -> Decimal:
    return round_cents(line.amount * fx_rate(line.currency, currency))


def invoice_subtotal(lines: Iterable[InvoiceLine], currency: str) -> Decimal:
    return sum((line_value(line, currency) for line in lines), Decimal(0))
