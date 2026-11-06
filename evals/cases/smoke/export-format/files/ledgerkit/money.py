from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def round_invoice_total(amount):
    value = Decimal(amount)
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def round_display_amount(amount):
    value = Decimal(amount)
    return value.quantize(CENTS, rounding=ROUND_HALF_EVEN)
