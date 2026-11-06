from datetime import UTC, datetime, timedelta

import pytest

from tidekit import (
    Reading,
    load_readings,
    reading_from_row,
    readings_between,
    readings_for_station,
)

AT = datetime(2026, 7, 1, 12, tzinfo=UTC)
HEADER = "station,date,time,level,unit,quality\n"


def test_row_in_metres_is_kept_as_is():
    reading = reading_from_row("HLX", "2026-07-01", "12:00", "1.25", "m", "good")
    assert reading == Reading("HLX", AT, 1.25)


def test_row_in_centimetres_is_converted():
    assert reading_from_row("HLX", "2026-07-01", "12:00", "125", "cm", "good").level_m == 1.25


def test_suspect_row_is_dropped():
    assert reading_from_row("HLX", "2026-07-01", "12:00", "1.25", "m", "suspect") is None


def test_unknown_unit_is_refused():
    with pytest.raises(ValueError, match="furlong"):
        reading_from_row("HLX", "2026-07-01", "12:00", "1", "furlong", "good")


def test_load_reads_every_file(tmp_path):
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text(HEADER + "HLX,2026-07-01,12:00,1.5,m,good\n")
    second.write_text(
        HEADER + "YRM,2026-07-01,12:00,2.5,m,good\n" + "YRM,2026-07-01,13:00,9,m,suspect\n"
    )
    assert [r.level_m for r in load_readings([first, second])] == [1.5, 2.5]


def test_station_selection_orders_by_time():
    late = Reading("HLX", AT + timedelta(hours=1), 2.0)
    early = Reading("HLX", AT, 1.0)
    other = Reading("YRM", AT, 5.0)
    assert readings_for_station([late, other, early], "HLX") == [early, late]


def test_window_includes_start_and_excludes_end():
    inside = Reading("HLX", AT, 1.0)
    at_end = Reading("HLX", AT + timedelta(hours=1), 2.0)
    assert readings_between([inside, at_end], AT, AT + timedelta(hours=1)) == [inside]
