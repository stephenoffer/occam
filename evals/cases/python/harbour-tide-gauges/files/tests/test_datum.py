from datetime import UTC, datetime

import pytest

from tidekit import Reading, datum_correctors, reduce_to_chart_datum

AT = datetime(2026, 7, 1, tzinfo=UTC)


def test_corrector_subtracts_the_offset():
    assert datum_correctors({"HLX": 0.25})["HLX"](2.0) == 1.75


def test_negative_offset_raises_the_level():
    assert datum_correctors({"SYD": -0.5})["SYD"](1.0) == 1.5


def test_readings_are_reduced_in_order():
    readings = [Reading("HLX", AT, 2.0), Reading("HLX", AT, 3.0)]
    assert [r.level_m for r in reduce_to_chart_datum(readings, {"HLX": 0.5})] == [1.5, 2.5]


def test_station_without_an_offset_is_an_error():
    with pytest.raises(KeyError):
        reduce_to_chart_datum([Reading("YRM", AT, 2.0)], {"HLX": 0.5})
