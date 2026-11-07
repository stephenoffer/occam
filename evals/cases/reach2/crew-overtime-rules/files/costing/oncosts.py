"""Employer on-costs added on top of wages in a forecast.

Rates are the ones finance publishes each April. Holiday accrual is the statutory 12.07% for
hourly-paid staff; bids that are priced inclusive of holiday leave it out with --no-holiday.
"""

from __future__ import annotations

from decimal import Decimal

ONCOST_COMPONENTS = {
    "employer_ni": Decimal("0.138"),
    "pension": Decimal("0.03"),
    "apprenticeship_levy": Decimal("0.005"),
    "holiday_accrual": Decimal("0.1207"),
}


def oncost_rate(exclude: tuple[str, ...] = ()) -> Decimal:
    unknown = set(exclude) - set(ONCOST_COMPONENTS)
    if unknown:
        raise KeyError(f"unknown on-cost components: {', '.join(sorted(unknown))}")
    return sum((rate for name, rate in ONCOST_COMPONENTS.items() if name not in exclude), Decimal(0))
