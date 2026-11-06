from decimal import Decimal

from orders.pricing import Coupon, apply_coupon


def test_percent_coupon():
    assert apply_coupon(Decimal("100"), Coupon("percent", Decimal("10"))) == Decimal("90")


def test_percent_coupon_capped():
    coupon = Coupon("percent", Decimal("50"), max_discount=Decimal("20"))
    assert apply_coupon(Decimal("100"), coupon) == Decimal("80")


def test_fixed_coupon():
    assert apply_coupon(Decimal("100"), Coupon("fixed", Decimal("5"))) == Decimal("95")
