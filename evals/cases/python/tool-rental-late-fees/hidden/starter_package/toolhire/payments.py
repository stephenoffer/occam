"""Deposit movements. The card processor integration writes through this journal."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Movement:
    kind: str
    rental_id: str
    cents: int


JOURNAL: list[Movement] = []


def capture_from_deposit(rental_id: str, cents: int) -> Movement:
    if cents <= 0:
        raise ValueError("a capture must be for a positive amount")
    movement = Movement("capture", rental_id, cents)
    JOURNAL.append(movement)
    return movement


def release_deposit(rental_id: str, cents: int) -> Movement:
    if cents <= 0:
        raise ValueError("a release must be for a positive amount")
    movement = Movement("release", rental_id, cents)
    JOURNAL.append(movement)
    return movement


def movements_for(rental_id: str) -> list[Movement]:
    return [movement for movement in JOURNAL if movement.rental_id == rental_id]
