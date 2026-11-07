from datetime import date, time
from decimal import Decimal

import pytest

from common.csvio import CsvError
from crew_factories import TIMESHEET_HEADER, write_csv
from timesheets.parse import load_timesheets


def test_loads_a_timesheet(tmp_path):
    path = write_csv(tmp_path / "t.csv", TIMESHEET_HEADER, [
        ["W1", "2026-11-02", "07:00", "15:30", "30", "QSY", "CC-420", "approved"],
    ])
    [shift] = load_timesheets(path)
    assert shift.work_date == date(2026, 11, 2)
    assert shift.start == time(7, 0)
    assert shift.hours == Decimal(8)
    assert shift.approved


def test_status_column_is_optional(tmp_path):
    path = write_csv(tmp_path / "t.csv", TIMESHEET_HEADER[:-1], [
        ["W1", "2026-11-02", "07:00", "15:00", "0", "QSY", "CC-420"],
    ])
    assert load_timesheets(path)[0].approved


def test_midnight_end_is_read_as_the_last_minute(tmp_path):
    path = write_csv(tmp_path / "t.csv", TIMESHEET_HEADER, [
        ["W1", "2026-11-02", "22:00", "24:00", "0", "NWK", "CC-410", "approved"],
    ])
    assert load_timesheets(path)[0].hours == Decimal(2)


@pytest.mark.parametrize("row, message", [
    (["W1", "2026-02-30", "07:00", "15:00", "0", "Q", "C", "approved"], "bad date"),
    (["W1", "2026-11-02", "7am", "15:00", "0", "Q", "C", "approved"], "bad time"),
    (["W1", "2026-11-02", "07:00", "15:00", "x", "Q", "C", "approved"], "bad break"),
    (["W1", "2026-11-02", "07:00", "15:00", "0", "Q", "C", "paid"], "unknown status"),
])
def test_bad_rows_say_where(tmp_path, row, message):
    path = write_csv(tmp_path / "t.csv", TIMESHEET_HEADER, [row])
    with pytest.raises(CsvError, match=message):
        load_timesheets(path)
