"""A fixed amount in its own currency, converted to the document's."""

from collections.abc import Mapping
from decimal import Decimal

from tidewater.core.money import round_cents
from tidewater.domain.adjustments.context import AdjustmentContext
from tidewater.domain.adjustments.conversion import conversion_rate


def compute(context: AdjustmentContext, params: Mapping[str, str]) -> Decimal:
    rate = conversion_rate(params["rate_source"], params["denominated_in"], context.currency)
    return round_cents(Decimal(params["amount"]) * rate)
