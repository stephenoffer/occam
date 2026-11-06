from datetime import UTC, date, datetime

import pytest

from tidekit import (
    HIGH_WATER,
    LOW_WATER,
    Reading,
    TideEvent,
    daily_extrema,
    mean_high_water,
    mean_low_water,
    mean_tidal_range,
)

AT = datetime(2026, 7, 1, 12, tzinfo=UTC)


def test_daily_extrema_gives_one_high_and_one_low_per_day():
    low = Reading("HLX", AT, 0.5)
    middle = Reading("HLX", AT, 1.0)
    high = Reading("HLX", AT, 2.5)
    assert daily_extrema([middle, high, low], "America/Halifax") == {date(2026, 7, 1): (low, high)}


def test_means_and_range():
    events = [
        TideEvent("HLX", HIGH_WATER, AT, 3.0),
        TideEvent("HLX", HIGH_WATER, AT, 2.0),
        TideEvent("HLX", LOW_WATER, AT, 0.5),
    ]
    assert mean_high_water(events) == 2.5
    assert mean_low_water(events) == 0.5
    assert mean_tidal_range(events) == 2.0


def test_mean_of_nothing_is_an_error():
    with pytest.raises(ValueError, match="no high_water"):
        mean_high_water([])
