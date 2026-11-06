from decimal import Decimal
from unittest.mock import Mock

from freightquote import pricing
from freightquote.models import Mode, Shipment


def test_money_rounds_half_up():
    assert pricing.money(Decimal("10.005")) == Decimal("10.01")
    assert pricing.money(Decimal("10.004")) == Decimal("10.00")


def test_chargeable_weight_uses_actual_when_heavier():
    shipment = Shipment("S", Decimal("500"), Decimal("1"), 1)
    assert pricing.chargeable_weight_kg(shipment, Mode.ROAD) == Decimal("500")


def test_chargeable_weight_uses_volumetric_when_bulkier():
    shipment = Shipment("S", Decimal("100"), Decimal("2"), 1)
    assert pricing.chargeable_weight_kg(shipment, Mode.ROAD) == Decimal("500")


def test_volumetric_factor_depends_on_mode():
    shipment = Shipment("S", Decimal("1"), Decimal("1"), 1)
    assert pricing.chargeable_weight_kg(shipment, Mode.AIR) == Decimal("167")
    assert pricing.chargeable_weight_kg(shipment, Mode.RAIL) == Decimal("200")


def test_volume_discount_tiers(monkeypatch):
    tiers = Mock(side_effect=lambda units: Decimal("0.05") if units >= 10 else Decimal("0"))
    monkeypatch.setattr(pricing, "volume_discount_rate", tiers)
    assert pricing.volume_discount_rate(12) == Decimal("0.05")
    assert pricing.volume_discount_rate(3) == Decimal("0")
    assert tiers.call_count == 2


def test_base_freight_adds_distance_and_weight(pallet, road_lane, road_rates):
    assert pricing.base_freight(pallet, road_lane, road_rates) == Decimal("520.00")


def test_base_freight_respects_minimum_charge(road_lane, road_rates):
    short = road_lane.__class__(
        "R2", "A", "B", Mode.ROAD, 10, road_lane.max_weight_kg, road_lane.max_volume_m3
    )
    light = Shipment("S", Decimal("5"), Decimal("0.01"), 1)
    assert pricing.base_freight(light, short, road_rates) == Decimal("85.00")


def test_small_orders_earn_no_discount_line():
    assert pricing.discount_line(Decimal("100"), 3) is None
