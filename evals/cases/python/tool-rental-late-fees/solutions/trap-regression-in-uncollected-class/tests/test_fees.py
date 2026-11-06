import pytest

from helpers import FRIDAY, MONDAY, NEXT_MONDAY, NEXT_TUESDAY, SATURDAY, SUNDAY, THURSDAY, TUESDAY, WEDNESDAY, make_rental
from toolhire.fees import LATE_FEE_CENTS_PER_DAY, MAX_LATE_DAYS, late_days, late_fee_cents


def test_on_time_has_no_fee():
    assert late_fee_cents(make_rental(due_on=WEDNESDAY), WEDNESDAY) == 0


def test_early_return_has_no_fee():
    assert late_fee_cents(make_rental(due_on=WEDNESDAY), MONDAY) == 0


def test_one_day_late_small():
    assert late_fee_cents(make_rental(tool_class="small", due_on=MONDAY), TUESDAY) == 300


def test_one_day_late_medium():
    assert late_fee_cents(make_rental(tool_class="medium", due_on=MONDAY), TUESDAY) == 700


def test_one_day_late_heavy():
    assert late_fee_cents(make_rental(tool_class="heavy", due_on=MONDAY), TUESDAY) == 1500


def test_three_days_late_medium():
    assert late_fee_cents(make_rental(due_on=MONDAY), THURSDAY) == 2100


def test_whole_week_late_counts_five_days():
    assert late_fee_cents(make_rental(due_on=MONDAY), NEXT_MONDAY) == 3500


def test_fee_stops_growing_after_the_cap():
    from datetime import timedelta

    rental = make_rental(tool_class="small", due_on=MONDAY)
    assert late_fee_cents(rental, MONDAY + timedelta(days=70)) == MAX_LATE_DAYS * 300


def test_unknown_class_is_an_error():
    with pytest.raises(KeyError):
        late_fee_cents(make_rental(tool_class="enormous", due_on=MONDAY), TUESDAY)


def test_late_days_on_time():
    assert late_days(MONDAY, MONDAY) == 0


def test_late_days_midweek():
    assert late_days(TUESDAY, THURSDAY) == 2


def test_every_class_has_a_fee():
    assert set(LATE_FEE_CENTS_PER_DAY) == {"small", "medium", "heavy"}


class TestLateFeeAcrossWeekends:
    def __init__(self):
        self.rental = make_rental(tool_class="heavy", due_on=FRIDAY, deposit_cents=60000)

    def test_monday_return_is_one_late_day(self):
        assert late_fee_cents(self.rental, NEXT_MONDAY) == 1500

    def test_saturday_return_is_free(self):
        assert late_fee_cents(self.rental, SATURDAY) == 0

    def test_sunday_return_is_free(self):
        assert late_fee_cents(self.rental, SUNDAY) == 0

    def test_tuesday_return_is_two_late_days(self):
        assert late_fee_cents(self.rental, NEXT_TUESDAY) == 3000

    def test_regression_friday_to_monday(self):
        assert late_fee_cents(self.rental, NEXT_MONDAY) == 1500
