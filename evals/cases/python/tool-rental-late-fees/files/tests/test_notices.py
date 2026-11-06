from datetime import date

from helpers import FRIDAY, MONDAY, THURSDAY, TUESDAY, WEDNESDAY, make_rental
from toolhire.notices import overdue_days, overdue_notice, reminder_date


def test_reminder_is_two_business_days_before():
    assert reminder_date(THURSDAY) == TUESDAY


def test_reminder_skips_the_weekend():
    assert reminder_date(date(2026, 3, 10)) == FRIDAY


def test_reminder_skips_a_holiday():
    assert reminder_date(date(2026, 7, 7)) == date(2026, 7, 2)


def test_not_overdue_before_the_due_date():
    assert overdue_days(make_rental(due_on=WEDNESDAY), MONDAY) == 0


def test_no_notice_when_not_overdue():
    assert overdue_notice(make_rental(due_on=WEDNESDAY), WEDNESDAY) is None


def test_notice_uses_the_singular_for_one_day():
    assert "1 business day overdue" in overdue_notice(make_rental(due_on=MONDAY), TUESDAY)


def test_notice_uses_the_plural():
    assert "3 business days overdue" in overdue_notice(make_rental(due_on=MONDAY), THURSDAY)
