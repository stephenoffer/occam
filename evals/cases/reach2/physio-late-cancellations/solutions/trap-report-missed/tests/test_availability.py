from datetime import date, datetime

from appointments import service
from scheduling.availability import free_slots, is_free
from scheduling.sessions import Session, slot_starts

TUESDAY = date(2026, 12, 8)


def times(slots):
    return [slot.strftime("%H:%M") for slot in slots]


def test_slots_fill_the_session():
    session = Session(1, "09:00", "17:00")
    starts = slot_starts(session, TUESDAY, 45)
    assert times(starts)[:3] == ["09:00", "09:45", "10:30"]
    assert times(starts)[-1] == "15:45"


def test_empty_day_is_all_free(db):
    assert len(free_slots(db, 1, TUESDAY)) == 10


def test_no_sessions_no_slots(db):
    assert free_slots(db, 2, date(2026, 12, 9)) == []


def test_booking_takes_the_slot(db, book):
    book(1, "2026-12-08T09:45")
    assert "09:45" not in times(free_slots(db, 1, TUESDAY))


def test_off_grid_booking_blocks_both_neighbours(db, book):
    book(1, "2026-12-08T10:00")
    free = times(free_slots(db, 1, TUESDAY))
    assert "09:45" not in free and "10:30" not in free


def test_completed_appointment_keeps_its_time(db, book):
    appointment = book(1, "2026-12-08T09:00")
    service.arrive(db, appointment.id, datetime(2026, 12, 8, 8, 55))
    service.complete(db, appointment.id, datetime(2026, 12, 8, 9, 45))
    assert not is_free(db, 1, datetime(2026, 12, 8, 9, 0), 45)


def test_late_cancellation_gives_the_time_back(db, book):
    appointment = book(1, "2026-12-08T09:00")
    service.cancel(db, appointment.id, datetime(2026, 12, 8, 7, 30))
    assert is_free(db, 1, datetime(2026, 12, 8, 9, 0), 45)


def test_cancellation_gives_the_time_back(db, book):
    appointment = book(1, "2026-12-08T09:00")
    service.cancel(db, appointment.id, datetime(2026, 12, 1, 12, 0))
    assert is_free(db, 1, datetime(2026, 12, 8, 9, 0), 45)
