from datetime import datetime

import pytest

from appointments import queries, service
from appointments.errors import InvalidMove, SlotUnavailable, TooEarly, TooLate
from appointments.status import Status
from scheduling.availability import free_slots

at = datetime.fromisoformat


def test_booking_records_an_event_and_queues_a_confirmation(db, book):
    appointment = book(1, "2026-12-08T10:00")
    assert appointment.status is Status.BOOKED
    assert queries.events(db, appointment.id) == [(Status.BOOKED, "2026-10-01T09:00")]
    message = db.execute("SELECT template, body FROM messages").fetchone()
    assert message["template"] == "booked"
    assert "Tue 8 Dec at 10:00" in message["body"]


def test_cannot_double_book(book):
    book(1, "2026-12-08T10:00")
    with pytest.raises(SlotUnavailable):
        book(2, "2026-12-08T10:30")


def test_cannot_book_outside_sessions(book):
    with pytest.raises(SlotUnavailable):
        book(1, "2026-12-08T16:30")
    with pytest.raises(SlotUnavailable):
        book(1, "2026-12-12T10:00")


def test_cannot_book_in_the_past(book):
    with pytest.raises(TooLate):
        book(1, "2026-12-08T10:00", booked_at="2026-12-08T11:00")


def test_full_visit(db, book):
    appointment = book(1, "2026-12-08T10:00")
    service.confirm(db, appointment.id, at("2026-12-07T18:05"))
    service.arrive(db, appointment.id, at("2026-12-08T09:50"))
    done = service.complete(db, appointment.id, at("2026-12-08T10:45"))
    assert done.status is Status.COMPLETED
    assert [status for status, _ in queries.events(db, appointment.id)] == [
        Status.BOOKED, Status.CONFIRMED, Status.ARRIVED, Status.COMPLETED]


def test_cancelling_ahead_frees_the_slot_and_texts_the_patient(db, book):
    appointment = book(1, "2026-12-08T10:30")
    cancelled = service.cancel(db, appointment.id, at("2026-12-05T12:00"))
    assert cancelled.status is Status.CANCELLED
    assert cancelled.cancelled_at == at("2026-12-05T12:00")
    assert at("2026-12-08T10:30") in free_slots(db, 1, at("2026-12-08T00:00").date())
    templates = [row["template"] for row in db.execute("SELECT template FROM messages ORDER BY id")]
    assert templates == ["booked", "cancelled"]


def test_cancelling_at_short_notice_still_frees_the_slot(db, book):
    appointment = book(1, "2026-12-08T10:30")
    cancelled = service.cancel(db, appointment.id, at("2026-12-08T08:00"))
    assert cancelled.status is Status.CANCELLED
    assert at("2026-12-08T10:30") in free_slots(db, 1, at("2026-12-08T00:00").date())


def test_cannot_cancel_once_started(db, book):
    appointment = book(1, "2026-12-08T10:00")
    with pytest.raises(TooLate):
        service.cancel(db, appointment.id, at("2026-12-08T10:05"))


def test_no_show_only_after_the_start(db, book):
    appointment = book(1, "2026-12-08T10:00")
    with pytest.raises(TooEarly):
        service.mark_no_show(db, appointment.id, at("2026-12-08T09:30"))
    missed = service.mark_no_show(db, appointment.id, at("2026-12-08T10:20"))
    assert missed.status is Status.NO_SHOW


def test_no_show_keeps_the_slot(db, book):
    appointment = book(1, "2026-12-08T10:00")
    service.mark_no_show(db, appointment.id, at("2026-12-08T10:20"))
    assert at("2026-12-08T10:00") not in free_slots(db, 1, at("2026-12-08T00:00").date())


def test_cancelled_appointment_cannot_be_completed(db, book):
    appointment = book(1, "2026-12-08T10:00")
    service.cancel(db, appointment.id, at("2026-12-05T12:00"))
    with pytest.raises(InvalidMove):
        service.complete(db, appointment.id, at("2026-12-08T10:45"))


def test_early_check_in_is_refused(db, book):
    appointment = book(1, "2026-12-08T10:00")
    with pytest.raises(TooEarly):
        service.arrive(db, appointment.id, at("2026-12-08T08:30"))
