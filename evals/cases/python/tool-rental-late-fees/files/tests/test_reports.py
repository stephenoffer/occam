from toolhire.models import Settlement
from toolhire.reports import late_fee_summary, worst_offenders


def settled(rental_id, late_days=0, fee=0, damage=0, released=1000):
    return Settlement(rental_id, late_days, fee, damage, fee + damage, released)


def test_summary_of_nothing():
    assert late_fee_summary([])["returns"] == 0


def test_summary_counts_late_returns():
    summary = late_fee_summary([settled("A"), settled("B", 2, 1400)])
    assert (summary["returns"], summary["late_returns"]) == (2, 1)


def test_summary_adds_money():
    summary = late_fee_summary([settled("A", 1, 700, 100, 500), settled("B", 2, 1400, 0, 200)])
    assert summary["late_fee_cents"] == 2100
    assert summary["damage_cents"] == 100
    assert summary["released_cents"] == 700


def test_worst_offenders_ranked_by_days():
    assert worst_offenders([settled("A", 1), settled("B", 4), settled("C", 2)]) == ["B", "C", "A"]


def test_worst_offenders_skips_on_time_returns():
    assert worst_offenders([settled("A"), settled("B", 1)]) == ["B"]


def test_worst_offenders_limit():
    assert worst_offenders([settled(name, 3) for name in "ABCDE"], limit=2) == ["A", "B"]
