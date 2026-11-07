from datetime import date

from ledger.periods import weeks_for_month


def test_a_month_covers_the_weeks_that_start_in_it():
    assert weeks_for_month("2026-11") == [date(2026, 11, d) for d in (2, 9, 16, 23, 30)]


def test_a_week_that_straddles_month_end_belongs_to_the_month_it_starts_in():
    assert date(2026, 9, 28) in weeks_for_month("2026-09")
    assert date(2026, 9, 28) not in weeks_for_month("2026-10")
