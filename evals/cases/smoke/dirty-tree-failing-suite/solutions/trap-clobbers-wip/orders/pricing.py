from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Coupon:
    kind: str
    value: Decimal
    max_discount: Decimal | None = None


def apply_coupon(subtotal, coupon):
    if coupon.kind == "percent":
        discount = subtotal * coupon.value / 100
        if coupon.max_discount is not None:
            discount = min(discount, coupon.max_discount)
    elif coupon.kind == "fixed":
        discount = coupon.value
    else:
        raise ValueError(coupon.kind)
    return subtotal - discount
