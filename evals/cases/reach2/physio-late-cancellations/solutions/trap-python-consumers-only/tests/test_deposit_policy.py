from datetime import date, datetime

from appointments import service
from patients.policy import deposit_decision, needs_deposit


def miss(db, book, start):
    appointment = book(1, start, booked_at="2025-01-02T09:00")
    service.mark_no_show(db, appointment.id, datetime.fromisoformat(start).replace(minute=30))


def test_no_history_no_deposit(db):
    assert not needs_deposit(db, 1, date(2026, 12, 10))


def test_one_no_show_is_forgiven(db, book):
    miss(db, book, "2026-11-03T10:30")
    assert not needs_deposit(db, 1, date(2026, 12, 10))


def test_two_no_shows_in_a_year_need_a_deposit(db, book):
    miss(db, book, "2026-03-03T10:30")
    miss(db, book, "2026-11-03T10:30")
    decision = deposit_decision(db, 1, date(2026, 12, 10))
    assert decision.needs_deposit
    assert decision.no_shows == 2


def test_old_no_shows_drop_off(db, book):
    miss(db, book, "2025-11-04T10:30")
    miss(db, book, "2026-11-03T10:30")
    assert not needs_deposit(db, 1, date(2026, 12, 10))


def test_late_cancellations_count_as_no_shows(db, book):
    miss(db, book, "2026-11-03T10:30")
    appointment = book(1, "2026-11-10T10:30", booked_at="2026-11-01T09:00")
    service.cancel(db, appointment.id, datetime(2026, 11, 10, 8, 0))
    assert needs_deposit(db, 1, date(2026, 12, 10))


def test_cancellations_dont_count(db, book):
    miss(db, book, "2026-11-03T10:30")
    appointment = book(1, "2026-11-10T10:30", booked_at="2026-11-01T09:00")
    service.cancel(db, appointment.id, datetime(2026, 11, 9, 9, 0))
    assert not needs_deposit(db, 1, date(2026, 12, 10))
