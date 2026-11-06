from datetime import UTC, date, datetime, timedelta

import pytest

from tidekit import HIGH_WATER, LOW_WATER, Reading, find_turning_points, local_day

AT = datetime(2026, 7, 1, tzinfo=UTC)


def series(levels, station="HLX"):
    return [Reading(station, AT + timedelta(hours=n), level) for n, level in enumerate(levels)]


def test_high_and_low_water_are_found():
    events = find_turning_points(series([1.0, 2.0, 1.0, 0.5, 1.0]))
    assert [(e.kind, e.level_m) for e in events] == [(HIGH_WATER, 2.0), (LOW_WATER, 0.5)]


def test_first_and_last_readings_are_not_turning_points():
    assert find_turning_points(series([3.0, 2.0, 1.0])) == []


def test_flat_top_is_not_a_turning_point():
    assert find_turning_points(series([1.0, 2.0, 2.0, 1.0])) == []


def test_mixed_stations_are_refused():
    with pytest.raises(ValueError, match="several stations"):
        find_turning_points(series([1.0]) + series([1.0], "YRM"))


def test_local_day_uses_the_station_timezone():
    assert local_day(datetime(2026, 7, 1, 2, tzinfo=UTC), "America/Halifax") == date(2026, 6, 30)
    assert local_day(datetime(2026, 7, 1, 4, tzinfo=UTC), "America/Halifax") == date(2026, 7, 1)
