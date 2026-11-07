from datetime import date

import pytest

from common.weeks import WeekError, parse_month, parse_week, week_days, week_start, weeks_starting_in


def test_week_start_is_the_monday():
    assert week_start(date(2026, 11, 8)) == date(2026, 11, 2)
    assert week_start(date(2026, 11, 2)) == date(2026, 11, 2)


def test_week_days_run_monday_to_sunday():
    days = week_days(date(2026, 11, 2))
    assert days[0] == date(2026, 11, 2) and days[-1] == date(2026, 11, 8)


def test_parse_week_rejects_a_wednesday():
    with pytest.raises(WeekError, match="Wednesday"):
        parse_week("2026-11-04")


def test_weeks_starting_in_november_2026():
    assert weeks_starting_in(2026, 11) == [date(2026, 11, d) for d in (2, 9, 16, 23, 30)]


def test_weeks_starting_in_a_month_that_starts_on_monday():
    assert weeks_starting_in(2027, 2)[0] == date(2027, 2, 1)


def test_parse_month():
    assert parse_month("2026-11") == (2026, 11)
    with pytest.raises(WeekError):
        parse_month("2026-13")
    with pytest.raises(WeekError):
        parse_month("November")
