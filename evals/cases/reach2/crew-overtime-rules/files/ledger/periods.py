"""Which pay weeks a month-end accrual covers.

A month's accrual covers the pay weeks that START in that month, Monday to Sunday, even when the
Sunday falls in the next month. Each pay week is therefore accrued exactly once.
"""

from __future__ import annotations

from datetime import date

from common.weeks import parse_month, weeks_starting_in


def weeks_for_month(text: str) -> list[date]:
    year, month = parse_month(text)
    return weeks_starting_in(year, month)
