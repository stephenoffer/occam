from datetime import date

from toolhire.models import Rental

# March 2026: the 2nd is a Monday.
MONDAY = date(2026, 3, 2)
TUESDAY = date(2026, 3, 3)
WEDNESDAY = date(2026, 3, 4)
THURSDAY = date(2026, 3, 5)
FRIDAY = date(2026, 3, 6)
SATURDAY = date(2026, 3, 7)
SUNDAY = date(2026, 3, 8)
NEXT_MONDAY = date(2026, 3, 9)
NEXT_TUESDAY = date(2026, 3, 10)


def make_rental(rental_id="R-100", tool_class="medium", due_on=MONDAY, deposit_cents=15000) -> Rental:
    return Rental(rental_id, "Ada Example", tool_class, date(2026, 2, 23), due_on, deposit_cents)
