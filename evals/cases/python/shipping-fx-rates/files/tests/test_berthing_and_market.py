from decimal import Decimal

from tidewater.domain.berthing.charges import spot_rate
from tidewater.domain.chartering.market import historic_spot_rate, spot_rate_index


def test_class_b_berth():
    assert spot_rate("B", Decimal("12")) == Decimal("5208.00")


def test_class_a_berth():
    assert spot_rate("A", Decimal("1")) == Decimal("588.00")


def test_historic_points():
    assert historic_spot_rate("AG-EAST", 2026) == Decimal("58.0")


def test_market_index():
    assert spot_rate_index("WAF-EAST", 2025, 2025) == Decimal("100")
