"""Appointment statuses and the moves allowed between them.

The integer values are stored in ``appointments.status`` and are the same codes the
practice system we migrated from used. Never renumber them: see
docs/adr/0001-status-codes-as-integers.md.
"""

from __future__ import annotations

from enum import IntEnum


class Status(IntEnum):
    BOOKED = 1
    CONFIRMED = 2
    ARRIVED = 3
    COMPLETED = 4
    CANCELLED = 5
    NO_SHOW = 6
    LATE_CANCELLED = 7

    @property
    def label(self) -> str:
        return self.name.lower()


TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.BOOKED: frozenset({Status.CONFIRMED, Status.ARRIVED, Status.CANCELLED, Status.LATE_CANCELLED,
                              Status.NO_SHOW}),
    Status.CONFIRMED: frozenset({Status.ARRIVED, Status.CANCELLED, Status.LATE_CANCELLED, Status.NO_SHOW}),
    Status.ARRIVED: frozenset({Status.COMPLETED}),
    Status.COMPLETED: frozenset(),
    Status.CANCELLED: frozenset(),
    Status.NO_SHOW: frozenset(),
    Status.LATE_CANCELLED: frozenset(),
}

TERMINAL = frozenset(status for status, onward in TRANSITIONS.items() if not onward)

# Still expected to happen: what reminders and the front desk care about.
UPCOMING = frozenset({Status.BOOKED, Status.CONFIRMED})

# A late cancellation counts as a no-show for everything except the slot, which it frees.
MISSED = frozenset({Status.NO_SHOW, Status.LATE_CANCELLED})


def can_move(current: Status, target: Status) -> bool:
    return target in TRANSITIONS[current]


def parse(label: str) -> Status:
    try:
        return Status[label.strip().upper().replace("-", "_")]
    except KeyError:
        raise ValueError(f"unknown status: {label!r}") from None
