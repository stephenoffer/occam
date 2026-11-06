"""A percentage of what has been priced so far."""

from collections.abc import Mapping
from decimal import Decimal

from tidewater.core.money import percent_of, round_cents
from tidewater.domain.adjustments.context import AdjustmentContext


def compute(context: AdjustmentContext, params: Mapping[str, str]) -> Decimal:
    return round_cents(percent_of(context.subtotal, Decimal(params["percent"])))
