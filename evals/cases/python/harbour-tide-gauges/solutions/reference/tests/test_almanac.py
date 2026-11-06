from datetime import UTC, date, datetime, timedelta

from tidekit import HIGH_WATER, Reading, tide_calendar

AT = datetime(2026, 7, 1, 12, tzinfo=UTC)
LEVELS = [1.0, 2.0, 1.0, 0.5, 1.0]


def series(station, start=AT):
    return [Reading(station, start + timedelta(hours=n), level) for n, level in enumerate(LEVELS)]


def test_other_stations_are_left_out_and_offset_is_the_stations_own():
    readings = series("HLX") + series("YRM")
    days = tide_calendar(
        "HLX",
        readings,
        {"HLX": 0.5, "YRM": 1.0},
        "America/Halifax",
        date(2026, 7, 1),
        date(2026, 7, 1),
    )
    assert [(e.station, e.kind, e.level_m) for e in days[date(2026, 7, 1)]][0] == (
        "HLX",
        HIGH_WATER,
        1.5,
    )


def test_events_fall_on_the_local_day():
    readings = series("HLX", datetime(2026, 7, 2, 1, tzinfo=UTC))
    days = tide_calendar(
        "HLX", readings, {"HLX": 0.0}, "America/Halifax", date(2026, 7, 1), date(2026, 7, 2)
    )
    assert len(days[date(2026, 7, 1)]) == 1
    assert len(days[date(2026, 7, 2)]) == 1
