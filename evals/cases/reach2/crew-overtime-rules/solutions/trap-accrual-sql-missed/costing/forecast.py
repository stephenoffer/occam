"""Pricing a planned roster.

Each worker's planned week is walked in shift order and split into base and premium time by the
same rule the pay run uses (payroll.hours.split_in_order), so a planned hour is priced the way it
will be paid. Premium time is priced at PREMIUM_FACTOR times base and charged to the site whose
shift it falls in, so a site that takes someone at the end of a long day or week carries it. Vacant shifts are priced
at the vacant rate with no premium, since nobody's week is known yet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable

from common.money import pennies
from common.weeks import week_start
from costing.inputs import PlannedShift
from payroll.hours import split_in_order

PREMIUM_FACTOR = Decimal("1.5")
DEFAULT_VACANT_RATE = Decimal("21.50")
ZERO = Decimal(0)


@dataclass(frozen=True)
class PricedShift:
    shift: PlannedShift
    base_hours: Decimal
    premium_hours: Decimal
    rate: Decimal

    @property
    def wages(self) -> Decimal:
        return self.base_hours * self.rate + self.premium_hours * self.rate * PREMIUM_FACTOR


@dataclass
class SiteForecast:
    site: str
    shifts: int = 0
    hours: Decimal = ZERO
    premium_hours: Decimal = ZERO
    raw_wages: Decimal = ZERO
    weeks: set[date] = field(default_factory=set)

    @property
    def wages(self) -> Decimal:
        return pennies(self.raw_wages)


def split_premium(planned: Iterable[PlannedShift]) -> list[tuple[PlannedShift, Decimal, Decimal]]:
    """(shift, base hours, premium hours) for every named worker's shift, walking each week in order."""
    weeks: dict[tuple[str, date], list[PlannedShift]] = defaultdict(list)
    for shift in planned:
        if not shift.vacant:
            weeks[(shift.worker_id, week_start(shift.day))].append(shift)
    result = []
    for key in sorted(weeks):
        ordered = sorted(weeks[key], key=lambda s: (s.day, s.start))
        split = split_in_order((s.day, s.hours) for s in ordered)
        result += [(shift, base, premium) for shift, (base, premium) in zip(ordered, split)]
    return result


def price(planned: list[PlannedShift], rates: dict[str, Decimal],
          vacant_rate: Decimal = DEFAULT_VACANT_RATE) -> list[PricedShift]:
    missing = sorted({s.worker_id for s in planned if not s.vacant and s.worker_id not in rates})
    if missing:
        raise KeyError(f"no base rate for {', '.join(missing)}")
    priced = [PricedShift(shift, base, premium, rates[shift.worker_id])
              for shift, base, premium in split_premium(planned)]
    priced += [PricedShift(shift, shift.hours, ZERO, vacant_rate) for shift in planned if shift.vacant]
    return priced


def by_site(priced: Iterable[PricedShift]) -> dict[str, SiteForecast]:
    sites: dict[str, SiteForecast] = {}
    for item in priced:
        site = sites.setdefault(item.shift.site, SiteForecast(item.shift.site))
        site.shifts += 1
        site.hours += item.base_hours + item.premium_hours
        site.premium_hours += item.premium_hours
        site.raw_wages += item.wages
        site.weeks.add(week_start(item.shift.day))
    return dict(sorted(sites.items()))
