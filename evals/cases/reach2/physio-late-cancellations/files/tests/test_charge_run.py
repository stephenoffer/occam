from datetime import datetime

from appointments import service
from billing.fees import load_fees
from billing.run import run_charges

FEES = load_fees()
NIGHT = datetime(2026, 12, 9, 2, 0)


def attend(db, appointment, start):
    service.arrive(db, appointment.id, start)
    service.complete(db, appointment.id, start.replace(minute=45))


def test_fee_schedule_loads():
    assert FEES.missed_appointment_pence == 3000
    assert FEES.treatment_for(45) == 5500
    assert FEES.treatment_for(60) == 7500


def test_missed_appointment_is_charged_once(db, book):
    appointment = book(1, "2026-12-08T10:00")
    service.mark_no_show(db, appointment.id, datetime(2026, 12, 8, 10, 20))
    first = run_charges(db, NIGHT, FEES)
    assert [(c.appointment_id, c.kind, c.amount_pence) for c in first] == [(appointment.id, "dna", 3000)]
    assert run_charges(db, NIGHT, FEES) == []


def test_self_funded_treatment_is_charged(db, book):
    appointment = book(1, "2026-12-08T09:00")
    attend(db, appointment, datetime(2026, 12, 8, 9, 0))
    charges = run_charges(db, NIGHT, FEES)
    assert [(c.kind, c.amount_pence) for c in charges] == [("treatment", 5500)]


def test_insurer_funded_treatment_is_not_charged_here(db, book):
    appointment = book(2, "2026-12-08T09:00")
    attend(db, appointment, datetime(2026, 12, 8, 9, 0))
    assert run_charges(db, NIGHT, FEES) == []


def test_cancellations_are_not_charged(db, book):
    appointment = book(1, "2026-12-08T10:00")
    service.cancel(db, appointment.id, datetime(2026, 12, 6, 15, 0))
    assert run_charges(db, NIGHT, FEES) == []


def test_nothing_due_before_the_start(db, book):
    appointment = book(1, "2026-12-08T10:00")
    service.mark_no_show(db, appointment.id, datetime(2026, 12, 8, 10, 20))
    assert run_charges(db, datetime(2026, 12, 8, 2, 0), FEES) == []
