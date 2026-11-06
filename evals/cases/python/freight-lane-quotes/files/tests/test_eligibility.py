from decimal import Decimal

from freightquote.eligibility import (
    dangerous_goods_allowed,
    is_eligible,
    meets_rail_minimum,
    within_air_unit_weight,
    within_volume_limit,
    within_weight_limit,
)
from freightquote.models import Shipment


def shipment(weight="100", volume="1", units=1, dg_class=None):
    return Shipment("S-1", Decimal(weight), Decimal(volume), units, dg_class)


def test_weight_rule_accepts_shipment_at_the_limit(road_lane):
    assert within_weight_limit(shipment(weight="18000"), road_lane)


def test_weight_rule_rejects_overweight_shipment(road_lane):
    assert not within_weight_limit(shipment(weight="18000.5"), road_lane)


def test_volume_rule_rejects_oversized_shipment(road_lane):
    assert not within_volume_limit(shipment(volume="81"), road_lane)


def test_dangerous_goods_rule_accepts_ordinary_freight_anywhere(rail_lane):
    assert dangerous_goods_allowed(shipment(), rail_lane)


def test_dangerous_goods_rule_rejects_lane_without_clearance(rail_lane):
    assert not dangerous_goods_allowed(shipment(dg_class="3"), rail_lane)


def test_rail_minimum_rejects_small_shipment(rail_lane):
    assert not meets_rail_minimum(shipment(weight="499"), rail_lane)


def test_air_unit_rule_rejects_heavy_units(air_lane):
    assert not within_air_unit_weight(shipment(weight="600", units=2), air_lane)


def test_air_unit_rule_accepts_light_units(air_lane):
    assert within_air_unit_weight(shipment(weight="600", units=4), air_lane)


def test_pallet_is_eligible_on_a_road_lane(pallet, road_lane):
    assert is_eligible(pallet, road_lane)


def test_pallet_is_eligible_on_a_rail_lane(pallet, rail_lane):
    assert is_eligible(pallet, rail_lane)
