from dataclasses import dataclass
from decimal import Decimal

from .loyalty_tiers import points_value


@dataclass(frozen=True)
class Coupon:
    kind: str
    value: Decimal
    max_discount: Decimal | None = None


def loyalty_discount(points):
    # sam: tier multipliers still need product sign-off
    return points_value(points)


def apply_coupon(subtotal, coupon, loyalty_points=0):
    if coupon.kind == "percent":
        discount = subtotal * coupon.value / 100
        if coupon.max_discount is not None:
            capped_share = coupon.max_discount / subtotal
            if coupon.value / 100 > capped_share:
                discount = coupon.max_discount
    elif coupon.kind == "fixed":
        discount = coupon.value
    else:
        raise ValueError(coupon.kind)
    discount += loyalty_discount(loyalty_points)  # sam: stacking rule TBD
    return subtotal - discount
