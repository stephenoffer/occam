from datetime import datetime

from appointments import service
from messaging.reminders import due_reminders, send_reminders

EVENING = datetime(2026, 12, 7, 18, 0)


def test_reminds_tomorrows_upcoming_appointments(db, book):
    first = book(1, "2026-12-08T09:00")
    second = book(2, "2026-12-08T10:30")
    service.confirm(db, second.id, datetime(2026, 12, 7, 12, 0))
    book(1, "2026-12-09T09:00")
    assert [a.id for a in due_reminders(db, EVENING)] == [first.id, second.id]


def test_cancelled_appointments_get_no_reminder(db, book):
    appointment = book(1, "2026-12-08T09:00")
    service.cancel(db, appointment.id, datetime(2026, 12, 7, 11, 0))
    assert due_reminders(db, EVENING) == []


def test_reminders_are_sent_once(db, book):
    book(1, "2026-12-08T09:00")
    assert len(send_reminders(db, EVENING)) == 1
    assert send_reminders(db, EVENING) == []


def test_patients_without_a_phone_are_skipped(db, book):
    book(3, "2026-12-08T09:00")
    assert send_reminders(db, EVENING) == []
