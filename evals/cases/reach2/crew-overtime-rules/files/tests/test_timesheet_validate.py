from crew_factories import shift
from timesheets.validate import problems


def test_clean_week_has_no_problems():
    shifts = [shift("W1", "2026-11-02", "07:00", "15:30", 30), shift("W1", "2026-11-03", "07:00", "15:30", 30)]
    assert problems(shifts, {"W1"}) == []


def test_reports_overlaps_on_the_same_day():
    shifts = [shift("W1", "2026-11-02", "07:00", "12:00"), shift("W1", "2026-11-02", "11:30", "16:00")]
    [problem] = problems(shifts)
    assert "overlap" in problem and "W1" in problem


def test_back_to_back_shifts_are_fine():
    shifts = [shift("W1", "2026-11-02", "07:00", "12:00"), shift("W1", "2026-11-02", "12:00", "16:00")]
    assert problems(shifts) == []


def test_reports_unknown_workers_and_reversed_shifts():
    found = problems([shift("W9", "2026-11-02", "15:00", "07:00"), shift("W8", "2026-11-03", "07:00", "08:00")],
                     {"W1"})
    assert any("ends at or before" in p for p in found)
    assert any("no pay rate" in p and "W8" in p for p in found)


def test_break_as_long_as_the_shift():
    [problem] = problems([shift("W1", "2026-11-02", "07:00", "08:00", 60)])
    assert "break" in problem
