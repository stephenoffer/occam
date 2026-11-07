from rostering.checks import warnings


def row(worker, day, start, end, unpaid=0):
    return {"site": "QSY", "worker_id": worker, "date": day, "start": start, "end": end,
            "unpaid_break_minutes": str(unpaid)}


def test_a_normal_week_has_no_warnings():
    assert warnings([row("W1", f"2026-11-0{d}", "07:30", "16:00", 30) for d in range(2, 7)]) == []


def test_short_rest_between_shifts():
    found = warnings([row("W1", "2026-11-02", "12:00", "22:00"), row("W1", "2026-11-03", "06:00", "14:00")])
    assert any("rest" in w for w in found)


def test_shift_longer_than_twelve_paid_hours():
    found = warnings([row("W1", "2026-11-02", "06:00", "19:00", 30)])
    assert any("12.5 paid hours" in w for w in found)


def test_seven_days_in_a_row():
    found = warnings([row("W1", f"2026-11-{d:02d}", "08:00", "12:00") for d in range(2, 9)])
    assert any("day 7 in a row" in w for w in found)


def test_week_over_the_planning_cap():
    found = warnings([row("W1", f"2026-11-0{d}", "06:00", "18:00") for d in range(2, 8)])
    assert any("72 planned hours" in w for w in found)


def test_vacant_shifts_are_not_checked():
    assert warnings([row("VACANT", "2026-11-02", "06:00", "20:00")]) == []
