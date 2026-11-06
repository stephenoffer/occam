"""Settling a rental when the tool comes back."""

from datetime import date

from toolhire.fees import late_days, late_fee_cents
from toolhire.models import Rental, Settlement
from toolhire.payments import capture_from_deposit, release_deposit


def settle_return(rental: Rental, returned_on: date, damage_cents: int = 0) -> Settlement:
    fee = late_fee_cents(rental, returned_on)
    captured = min(fee + damage_cents, rental.deposit_cents)
    released = rental.deposit_cents - captured
    if captured:
        capture_from_deposit(rental.rental_id, captured)
    if released:
        release_deposit(rental.rental_id, released)
    return Settlement(
        rental_id=rental.rental_id,
        late_days=late_days(rental.due_on, returned_on),
        late_fee_cents=fee,
        damage_cents=damage_cents,
        captured_cents=captured,
        released_cents=released,
    )
