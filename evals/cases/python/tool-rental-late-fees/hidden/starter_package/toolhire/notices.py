"""Customer reminders and overdue notices."""

from datetime import date

from toolhire.models import Rental
from toolhire.workdays import business_days_between, previous_business_day

REMINDER_LEAD_BUSINESS_DAYS = 2


def reminder_date(due_on: date) -> date:
    day = due_on
    for _ in range(REMINDER_LEAD_BUSINESS_DAYS):
        day = previous_business_day(day)
    return day


def overdue_days(rental: Rental, on: date) -> int:
    return business_days_between(rental.due_on, on)


def overdue_notice(rental: Rental, on: date) -> str | None:
    days = overdue_days(rental, on)
    if days <= 0:
        return None
    unit = "business day" if days == 1 else "business days"
    return f"Rental {rental.rental_id} for {rental.customer} is {days} {unit} overdue."
