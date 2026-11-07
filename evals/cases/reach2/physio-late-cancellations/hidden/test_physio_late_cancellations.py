"""Late cancellations: recorded as their own status, free the slot, and otherwise count as no-shows.

Everything goes through the command lines the desk app and cron use, against a fresh database
per test. Appointment times are in December 2026, after the change goes live. Clinician 1 works
Monday to Friday, 09:00-17:00, in 45-minute slots (09:00, 09:45, 10:30, 11:15, ...).
"""

import json
from datetime import datetime, timedelta

import pytest

SEED = {
    "clinics": [{"id": 1, "name": "Leith Walk", "phone": "0131 496 0123"}],
    "clinicians": [
        {"id": 1, "name": "Aisha Patel", "clinic_id": 1, "slot_minutes": 45,
         "sessions": [{"weekday": day, "starts": "09:00", "ends": "17:00"} for day in range(5)]},
    ],
    "patients": [
        {"id": n, "name": name, "phone": f"07700 90{n:04d}", "funding": "insurer", "registered_on": "2025-05-01"}
        for n, name in enumerate(["Fiona MacLeod", "Daniel Okafor", "Eilidh Grant", "Ross Henderson",
                                  "Isla Murray", "Hamish Boyd"], start=1)
    ],
}
BOOKED_AT = "2026-11-20T09:00"


def later(start, minutes):
    return (datetime.fromisoformat(start) + timedelta(minutes=minutes)).isoformat(timespec="minutes")


class Clinic:
    def __init__(self, py, directory):
        self.py = py
        self.db = str(directory / "clinic.db")
        seed = directory / "seed.json"
        seed.write_text(json.dumps(SEED))
        self.cli("clinicdb", "init", as_json=False)
        self.cli("clinicdb", "seed", str(seed))

    def cli(self, module, *args, as_json=True):
        done = self.py("-m", module, "--db", self.db, *args, *(["--json"] if as_json else []))
        assert done.returncode == 0, f"python -m {module} {' '.join(args)} failed:\n{done.stderr[-2000:]}"
        return json.loads(done.stdout) if as_json else done.stdout

    def book(self, patient, start):
        return self.cli("appointments", "book", "--patient", str(patient), "--clinician", "1",
                        "--start", start, "--at", BOOKED_AT)["id"]

    def cancel(self, appointment, at):
        self.cli("appointments", "cancel", str(appointment), "--at", at)

    def no_show(self, appointment, start):
        self.cli("appointments", "no-show", str(appointment), "--at", later(start, 20))

    def attend(self, appointment, start):
        self.cli("appointments", "arrive", str(appointment), "--at", start)
        self.cli("appointments", "complete", str(appointment), "--at", later(start, 40))

    def status(self, patient, appointment):
        history = self.cli("appointments", "history", str(patient))
        return next(a["status"] for a in history["appointments"] if a["id"] == appointment)

    def free(self, day):
        return self.cli("scheduling", "free", "1", day)["free"]

    def charge_run(self, at):
        self.cli("billing", "run", "--at", at)

    def charged(self, patient, appointment):
        """Total charged for one appointment, from the patient's statement."""
        lines = self.cli("billing", "statement", str(patient))["lines"]
        return sum(line["amount_pence"] for line in lines if line["appointment_id"] == appointment)

    def needs_deposit(self, patient, on):
        return self.cli("patients", "deposit", str(patient), "--on", on)["needs_deposit"]

    def month(self, month):
        figures = self.cli("reports", "monthly", "--month", month)
        return next(entry for entry in figures["clinicians"] if entry["clinician_id"] == 1)


@pytest.fixture
def clinic(py, tmp_path):
    return Clinic(py, tmp_path)


def test_late_cancellation_is_recorded_and_frees_the_slot(clinic):
    appointment = clinic.book(1, "2026-12-08T10:30")
    clinic.cancel(appointment, "2026-12-07T15:30")  # 19 hours ahead

    status = clinic.status(1, appointment)
    # Its own status, whatever it's called: not an ordinary cancellation, and not a no-show either.
    ordinary = clinic.book(2, "2026-12-09T10:30")
    clinic.cancel(ordinary, "2026-12-07T09:00")  # 49 hours ahead
    missed = clinic.book(3, "2026-12-08T09:00")
    clinic.no_show(missed, "2026-12-08T09:00")
    assert status not in (clinic.status(2, ordinary), clinic.status(3, missed)), f"cancelled 19 hours ahead, recorded as {status!r}"
    assert "10:30" in clinic.free("2026-12-08"), "the late-cancelled slot isn't offered again"
    rebooked = clinic.cli("appointments", "book", "--patient", "2", "--clinician", "1",
                          "--start", "2026-12-08T10:30", "--at", "2026-12-07T16:00")
    assert rebooked["status"] == "booked"


def test_late_cancellation_is_charged_the_missed_appointment_fee(clinic):
    late = clinic.book(1, "2026-12-08T10:30")
    missed = clinic.book(2, "2026-12-08T09:00")
    ordinary = clinic.book(3, "2026-12-08T12:00")
    clinic.cancel(late, "2026-12-07T15:30")
    clinic.no_show(missed, "2026-12-08T09:00")
    clinic.cancel(ordinary, "2026-12-06T09:00")
    clinic.charge_run("2026-12-09T02:00")

    fee = clinic.charged(2, missed)
    assert fee > 0, "the no-show wasn't charged, so there is nothing to compare with"
    assert clinic.charged(1, late) == fee, "a late cancellation should be charged the missed-appointment fee"
    assert clinic.charged(3, ordinary) == 0, "a cancellation two days ahead shouldn't be charged"


def test_late_cancellation_counts_toward_the_deposit_rule(clinic):
    for patient, missed_start, other_start, cancelled_at in [
        (4, "2026-12-03T09:00", "2026-12-08T11:15", "2026-12-08T08:00"),  # late: 3 h 15 min ahead
        (5, "2026-12-03T09:45", "2026-12-08T13:30", "2026-12-05T10:00"),  # ordinary: 3 days ahead
    ]:
        clinic.no_show(clinic.book(patient, missed_start), missed_start)
        clinic.cancel(clinic.book(patient, other_start), cancelled_at)

    assert clinic.needs_deposit(4, "2026-12-10") is True, "a no-show plus a late cancellation should need a deposit"
    assert clinic.needs_deposit(5, "2026-12-10") is False, "an ordinary cancellation shouldn't count"


def test_monthly_report_counts_late_cancellations_as_dna(clinic):
    for patient, start in [(1, "2026-12-01T09:00"), (2, "2026-12-01T09:45")]:
        clinic.attend(clinic.book(patient, start), start)
    clinic.no_show(clinic.book(3, "2026-12-02T09:00"), "2026-12-02T09:00")
    clinic.cancel(clinic.book(4, "2026-12-08T10:30"), "2026-12-07T15:30")  # late
    clinic.cancel(clinic.book(5, "2026-12-09T09:00"), "2026-12-05T09:00")  # ordinary

    figures = clinic.month("2026-12")
    assert figures["dna"] == 2, f"one no-show and one late cancellation, but the figures show {figures['dna']} DNA"
    assert figures["dna_rate"] == pytest.approx(0.5, abs=0.001)


def test_cancelling_a_day_or_more_ahead_is_unchanged(clinic):
    exactly_a_day = clinic.book(1, "2026-12-08T10:30")
    days_ahead = clinic.book(2, "2026-12-09T09:00")
    clinic.cancel(exactly_a_day, "2026-12-07T10:30")
    clinic.cancel(days_ahead, "2026-12-06T09:00")

    assert clinic.status(1, exactly_a_day) == "cancelled"
    assert clinic.status(2, days_ahead) == "cancelled"
    assert "10:30" in clinic.free("2026-12-08")
    clinic.charge_run("2026-12-10T02:00")
    assert clinic.charged(1, exactly_a_day) == 0
    assert clinic.charged(2, days_ahead) == 0
    assert clinic.needs_deposit(1, "2026-12-10") is False
    figures = clinic.month("2026-12")
    assert (figures["dna"], figures["cancellations"]) == (0, 2)
