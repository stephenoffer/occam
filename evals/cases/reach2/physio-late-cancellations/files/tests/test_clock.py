from datetime import date, datetime

import pytest

from common.clock import day_bounds, human, month_bounds, parse_at, stored


def test_parse_drops_seconds():
    assert parse_at("2026-12-08T10:00:59") == datetime(2026, 12, 8, 10, 0)


def test_offsets_are_refused():
    with pytest.raises(ValueError):
        parse_at("2026-12-08T10:00+00:00")


def test_stored_round_trip():
    assert stored(parse_at("2026-12-08T10:00")) == "2026-12-08T10:00"


def test_day_bounds():
    assert day_bounds(date(2026, 12, 31)) == ("2026-12-31T00:00", "2027-01-01T00:00")


def test_month_bounds_wrap_the_year():
    assert month_bounds("2026-12") == ("2026-12-01T00:00", "2027-01-01T00:00")
    with pytest.raises(ValueError):
        month_bounds("2026-13")


def test_human():
    assert human(datetime(2026, 12, 8, 10, 0)) == "Tue 8 Dec at 10:00"
