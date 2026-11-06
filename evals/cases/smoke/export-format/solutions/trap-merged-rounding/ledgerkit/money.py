from decimal import ROUND_HALF_EVEN, Decimal

CENTS = Decimal("0.01")


def _round(amount):
    return Decimal(amount).quantize(CENTS, rounding=ROUND_HALF_EVEN)


round_invoice_total = _round
round_display_amount = _round
