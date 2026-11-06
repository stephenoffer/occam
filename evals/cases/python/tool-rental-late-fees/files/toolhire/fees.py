"""Late fees, per the late fee policy."""

from datetime import date

from toolhire.models import Rental
from toolhire.workdays import business_days_between

LATE_FEE_CENTS_PER_DAY = {"small": 300, "medium": 700, "heavy": 1500}
MAX_LATE_DAYS = 10


def late_days(due_on: date, returned_on: date) -> int:
    return business_days_between(due_on, returned_on)


def late_fee_cents(rental: Rental, returned_on: date) -> int:
    days = min(late_days(rental.due_on, returned_on), MAX_LATE_DAYS)
    return days * LATE_FEE_CENTS_PER_DAY[rental.tool_class]
