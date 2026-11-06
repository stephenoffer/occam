"""Opening and extending rentals."""

from dataclasses import replace
from datetime import date, timedelta

from toolhire.catalog import lookup
from toolhire.models import Rental
from toolhire.workdays import is_business_day, next_business_day


def due_date(start_on: date, hire_days: int) -> date:
    """Due back at the end of the hire, moved on to the next business day if that isn't one."""
    if hire_days < 1:
        raise ValueError("a hire is at least one day")
    due = start_on + timedelta(days=hire_days)
    return due if is_business_day(due) else next_business_day(due)


def open_rental(rental_id: str, customer: str, sku: str, start_on: date, hire_days: int) -> Rental:
    tool = lookup(sku)
    return Rental(rental_id, customer, tool.tool_class, start_on, due_date(start_on, hire_days), tool.deposit_cents)


def extend_rental(rental: Rental, extra_days: int) -> Rental:
    if extra_days < 1:
        raise ValueError("an extension is at least one day")
    due = rental.due_on + timedelta(days=extra_days)
    return replace(rental, due_on=due if is_business_day(due) else next_business_day(due))
