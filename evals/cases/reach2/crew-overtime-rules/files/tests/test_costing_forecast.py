from datetime import date, time
from decimal import Decimal

import pytest

from costing.forecast import by_site, price, split_premium
from costing.inputs import PlannedShift


def planned(site, worker, day, start, end, unpaid=0):
    return PlannedShift(site, worker, date.fromisoformat(day), time.fromisoformat(start), time.fromisoformat(end),
                        unpaid)


RATES = {"W1": Decimal("20.00"), "W2": Decimal("18.00")}


def test_a_forty_hour_plan_has_no_premium():
    plan = [planned("QSY", "W1", f"2026-11-0{d}", "07:00", "15:30", 30) for d in range(2, 7)]
    assert all(premium == 0 for _, _, premium in split_premium(plan))


def test_premium_lands_on_the_site_where_the_hours_fall():
    plan = [planned("QSY", "W1", f"2026-11-0{d}", "07:00", "15:30", 30) for d in range(2, 7)]
    plan.append(planned("NWK", "W1", "2026-11-07", "08:00", "14:00"))
    sites = by_site(price(plan, RATES))
    assert sites["QSY"].premium_hours == 0
    assert sites["NWK"].premium_hours == Decimal(6)
    assert sites["NWK"].wages == Decimal("180.00")


def test_the_week_is_walked_in_date_order_whatever_the_file_order():
    plan = [planned("NWK", "W1", "2026-11-07", "08:00", "14:00")]
    plan += [planned("QSY", "W1", f"2026-11-0{d}", "07:00", "15:30", 30) for d in range(6, 1, -1)]
    sites = by_site(price(plan, RATES))
    assert sites["NWK"].premium_hours == Decimal(6)


def test_three_long_days_are_all_base_time():
    plan = [planned("MLT", "W2", f"2026-11-0{d}", "07:00", "19:30", 30) for d in range(2, 5)]
    site = by_site(price(plan, RATES))["MLT"]
    assert (site.hours, site.premium_hours, site.wages) == (Decimal(36), Decimal(0), Decimal("648.00"))


def test_weeks_are_separate():
    plan = [planned("QSY", "W1", f"2026-11-{d:02d}", "07:00", "17:00") for d in (2, 3, 4, 5, 9, 10, 11, 12)]
    site = by_site(price(plan, RATES))["QSY"]
    assert site.premium_hours == 0
    assert len(site.weeks) == 2


def test_vacant_shifts_are_priced_without_premium():
    plan = [planned("NWK", "VACANT", f"2026-11-0{d}", "06:00", "19:00") for d in range(2, 8)]
    site = by_site(price(plan, RATES, vacant_rate=Decimal("20")))["NWK"]
    assert site.premium_hours == 0
    assert site.wages == Decimal("1560.00")


def test_a_named_worker_without_a_rate_is_an_error():
    with pytest.raises(KeyError, match="W9"):
        price([planned("NWK", "W9", "2026-11-02", "07:00", "15:00")], RATES)
