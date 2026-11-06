from decimal import Decimal

from freightquote.models import Shipment
from freightquote.surcharges import (
    fuel_surcharge,
    oversize_surcharge,
    remote_area_surcharge,
    surcharges_for,
)


def test_fuel_line_rounds_to_cents():
    assert fuel_surcharge(Decimal("100.10"), Decimal("0.125")).amount == Decimal("12.51")


def test_oversize_applies_above_threshold_only():
    assert oversize_surcharge(Shipment("S", Decimal("1"), Decimal("20"), 1)) is None
    line = oversize_surcharge(Shipment("S", Decimal("1"), Decimal("22"), 1))
    assert line is not None
    assert line.amount == Decimal("25.00")


def test_remote_area_applies_to_remote_destinations(air_lane, road_lane):
    assert remote_area_surcharge(road_lane) is None
    line = remote_area_surcharge(air_lane)
    assert line is not None
    assert line.amount == Decimal("75.00")


def test_surcharges_for_ordinary_pallet_is_fuel_only(pallet, road_lane):
    lines = surcharges_for(pallet, road_lane, Decimal("100"), Decimal("0.1"))
    assert [line.label for line in lines] == ["fuel"]


def test_surcharges_keep_invoice_order(air_lane):
    big = Shipment("S", Decimal("100"), Decimal("21"), 1)
    lines = surcharges_for(big, air_lane, Decimal("100"), Decimal("0.1"))
    assert [line.label for line in lines] == ["fuel", "oversize", "remote area"]
