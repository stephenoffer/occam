from datetime import date

import pytest

from helpers import FRIDAY, MONDAY, NEXT_MONDAY, make_rental
from toolhire.rentals import due_date, extend_rental, open_rental


def test_due_date_on_a_business_day():
    assert due_date(MONDAY, 3) == date(2026, 3, 5)


def test_due_date_rolls_past_the_weekend():
    assert due_date(MONDAY, 5) == NEXT_MONDAY


def test_due_date_rolls_past_a_holiday():
    assert due_date(date(2026, 9, 4), 3) == date(2026, 9, 8)


def test_hire_needs_at_least_a_day():
    with pytest.raises(ValueError):
        due_date(MONDAY, 0)


def test_open_rental_takes_class_and_deposit_from_the_catalog():
    rental = open_rental("R-1", "Ada Example", "TOWER", MONDAY, 2)
    assert (rental.tool_class, rental.deposit_cents) == ("heavy", 30000)


def test_extend_moves_the_due_date():
    assert extend_rental(make_rental(due_on=MONDAY), 2).due_on == date(2026, 3, 4)


def test_extend_rolls_past_the_weekend():
    assert extend_rental(make_rental(due_on=FRIDAY), 1).due_on == NEXT_MONDAY


def test_extension_needs_at_least_a_day():
    with pytest.raises(ValueError):
        extend_rental(make_rental(), 0)
