from datetime import date, timedelta

from helpers import FRIDAY, MONDAY, NEXT_MONDAY, SATURDAY, SUNDAY, THURSDAY, TUESDAY, WEDNESDAY
from toolhire.workdays import HOLIDAYS, business_days_between, is_business_day, next_business_day, previous_business_day


def test_same_day_is_zero():
    assert business_days_between(MONDAY, MONDAY) == 0


def test_earlier_end_is_zero():
    assert business_days_between(WEDNESDAY, MONDAY) == 0


def test_next_day_is_one():
    assert business_days_between(MONDAY, TUESDAY) == 1


def test_counts_within_a_week():
    assert business_days_between(MONDAY, THURSDAY) == 3


def test_monday_to_friday():
    assert business_days_between(MONDAY, FRIDAY) == 4


def test_counts_across_a_weekend():
    assert business_days_between(FRIDAY, NEXT_MONDAY) == 1


def test_whole_week_is_five():
    assert business_days_between(MONDAY, NEXT_MONDAY) == 5


def test_whole_week_from_wednesday():
    assert business_days_between(WEDNESDAY, WEDNESDAY + timedelta(days=7)) == 5


def test_four_whole_weeks():
    assert business_days_between(TUESDAY, TUESDAY + timedelta(days=28)) == 20


def test_memorial_day_is_not_counted():
    assert business_days_between(date(2026, 5, 18), date(2026, 5, 25)) == 4


def test_holiday_on_the_friday_is_not_counted():
    assert business_days_between(date(2026, 7, 2), date(2026, 7, 3)) == 0


def test_thanksgiving_week():
    assert business_days_between(date(2026, 11, 23), date(2026, 11, 27)) == 3


def test_holidays_fall_on_weekdays_this_year():
    assert all(holiday.weekday() < 5 for holiday in HOLIDAYS)


def test_weekday_is_a_business_day():
    assert is_business_day(MONDAY)


def test_saturday_is_not_a_business_day():
    assert not is_business_day(SATURDAY)


def test_sunday_is_not_a_business_day():
    assert not is_business_day(SUNDAY)


def test_holiday_is_not_a_business_day():
    assert not is_business_day(date(2026, 12, 25))


def test_next_business_day_skips_the_weekend():
    assert next_business_day(FRIDAY) == NEXT_MONDAY


def test_next_business_day_midweek():
    assert next_business_day(TUESDAY) == WEDNESDAY


def test_next_business_day_skips_a_holiday():
    assert next_business_day(date(2026, 9, 4)) == date(2026, 9, 8)


def test_previous_business_day_skips_the_weekend():
    assert previous_business_day(NEXT_MONDAY) == FRIDAY


def test_previous_business_day_skips_a_holiday():
    assert previous_business_day(date(2026, 7, 6)) == date(2026, 7, 2)


def test_two_whole_weeks():
    assert business_days_between(MONDAY, MONDAY + timedelta(days=14)) == 10
