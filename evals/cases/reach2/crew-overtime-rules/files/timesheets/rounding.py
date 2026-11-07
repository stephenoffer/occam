"""Worked time is rounded to the nearest quarter hour per shift (ADR 0001)."""

from __future__ import annotations

from decimal import Decimal

QUARTER = 15


def to_quarter_hours(minutes: int) -> Decimal:
    """Minutes worked on one shift, rounded to the nearest 15 minutes, as Decimal hours.

    Minutes are whole numbers, so a tie (7.5 minutes past a quarter) can't happen.
    """
    if minutes < 0:
        raise ValueError("negative worked time")
    quarters = (minutes + QUARTER // 2) // QUARTER
    return Decimal(quarters * QUARTER) / Decimal(60)
