from datetime import date
from decimal import Decimal

from crew_factories import shift
from payroll.hours import split_all, split_week

WEEK = date(2026, 11, 2)


def days(worker, dates, start, end, unpaid=0):
    return [shift(worker, f"2026-11-{day:02d}", start, end, unpaid) for day in dates]


def test_a_forty_hour_week_is_all_regular():
    hours = split_week("W1", WEEK, days("W1", range(2, 7), "07:00", "15:30", 30))
    assert (hours.regular, hours.overtime) == (Decimal(40), Decimal(0))


def test_hours_past_forty_in_the_week_are_overtime():
    shifts = days("W1", range(2, 7), "07:00", "15:30", 30) + [shift("W1", "2026-11-07", "07:00", "13:00")]
    hours = split_week("W1", WEEK, shifts)
    assert (hours.regular, hours.overtime) == (Decimal(40), Decimal(6))
    assert hours.total == Decimal(46)


def test_hours_past_ten_in_a_day_are_overtime_even_under_forty():
    hours = split_week("W1", WEEK, days("W1", range(2, 5), "07:00", "19:30", 30))
    assert (hours.regular, hours.overtime) == (Decimal(30), Decimal(6))


def test_daily_overtime_does_not_count_toward_the_forty():
    shifts = days("W1", range(2, 6), "07:00", "19:30", 30) + [shift("W1", "2026-11-06", "07:00", "11:00")]
    hours = split_week("W1", WEEK, shifts)
    assert (hours.regular, hours.overtime) == (Decimal(40), Decimal(12))


def test_split_shifts_on_one_day_are_added_up():
    shifts = [shift("W1", "2026-11-02", "06:00", "12:00"), shift("W1", "2026-11-02", "13:00", "19:00")]
    hours = split_week("W1", WEEK, shifts)
    assert (hours.regular, hours.overtime) == (Decimal(10), Decimal(2))


def test_quarter_hours_carry_into_overtime():
    hours = split_week("W1", WEEK, days("W1", range(2, 7), "07:00", "15:45", 30))
    assert (hours.regular, hours.overtime) == (Decimal(40), Decimal("1.25"))


def test_other_weeks_other_workers_and_unapproved_shifts_do_not_count():
    shifts = days("W1", range(2, 7), "07:00", "15:30", 30) + [
        shift("W1", "2026-11-01", "07:00", "19:00"),
        shift("W1", "2026-11-09", "07:00", "19:00"),
        shift("W1", "2026-11-07", "07:00", "19:00", status="submitted"),
        shift("W2", "2026-11-07", "07:00", "19:00"),
    ]
    hours = split_week("W1", WEEK, shifts)
    assert (hours.regular, hours.overtime) == (Decimal(40), Decimal(0))


def test_split_all_has_everyone_with_an_approved_shift():
    shifts = days("W2", range(2, 4), "07:00", "15:00") + days("W1", [2], "07:00", "15:00") + [
        shift("W3", "2026-11-02", "07:00", "15:00", status="draft")]
    result = split_all(shifts, WEEK)
    assert list(result) == ["W1", "W2"]
    assert result["W2"].regular == Decimal(16)
