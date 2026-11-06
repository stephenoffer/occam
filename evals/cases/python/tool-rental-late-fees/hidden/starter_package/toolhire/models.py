from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Rental:
    rental_id: str
    customer: str
    tool_class: str
    start_on: date
    due_on: date
    deposit_cents: int


@dataclass(frozen=True)
class Settlement:
    rental_id: str
    late_days: int
    late_fee_cents: int
    damage_cents: int
    captured_cents: int
    released_cents: int
