from datetime import datetime, timedelta

from appointments import service
from reports.monthly import dna_rate, monthly
from reports.render import render


def visit(db, book, start, outcome, patient=1):
    appointment = book(patient, start)
    when = datetime.fromisoformat(start)
    if outcome == "attended":
        service.arrive(db, appointment.id, when)
        service.complete(db, appointment.id, when.replace(minute=45))
    elif outcome == "missed":
        service.mark_no_show(db, appointment.id, when.replace(minute=20))
    elif outcome == "cancelled":
        service.cancel(db, appointment.id, datetime(2026, 11, 20, 12, 0))
    elif outcome == "cancelled late":
        service.cancel(db, appointment.id, when - timedelta(hours=3))
    return appointment


def test_dna_rate():
    assert dna_rate(3, 1) == 0.25
    assert dna_rate(0, 0) is None
    assert dna_rate(2, 1) == 0.333


def test_month_figures_per_clinician(db, book):
    visit(db, book, "2026-12-01T09:00", "attended")
    visit(db, book, "2026-12-01T10:00", "attended", patient=2)
    visit(db, book, "2026-12-02T09:00", "attended")
    visit(db, book, "2026-12-03T09:00", "missed")
    visit(db, book, "2026-12-04T09:00", "cancelled")
    visit(db, book, "2026-11-30T09:00", "missed")

    figures = monthly(db, "2026-12").as_dict()
    aisha = figures["clinicians"][0]
    assert aisha["clinician"] == "Aisha Patel"
    assert (aisha["booked"], aisha["attended"], aisha["cancellations"], aisha["dna"]) == (5, 3, 1, 1)
    assert aisha["dna_rate"] == 0.25
    assert aisha["treatment_minutes"] == 135
    assert figures["totals"]["dna"] == 1


def test_late_cancellations_count_as_dna(db, book):
    visit(db, book, "2026-12-01T09:00", "attended")
    visit(db, book, "2026-12-02T09:00", "missed")
    visit(db, book, "2026-12-03T09:00", "cancelled late")
    visit(db, book, "2026-12-04T09:00", "cancelled")
    aisha = monthly(db, "2026-12").as_dict()["clinicians"][0]
    assert (aisha["cancellations"], aisha["dna"], aisha["dna_rate"]) == (1, 2, 0.667)


def test_idle_clinician_has_no_rate(db):
    figures = monthly(db, "2026-12").as_dict()
    callum = next(entry for entry in figures["clinicians"] if entry["clinician"] == "Callum Reid")
    assert callum["booked"] == 0 and callum["dna_rate"] is None


def test_new_patients(db, book):
    visit(db, book, "2026-11-03T09:00", "attended")
    visit(db, book, "2026-12-01T09:00", "attended")
    visit(db, book, "2026-12-01T10:00", "attended", patient=2)
    assert monthly(db, "2026-12").new_patients == 1


def test_render_has_a_totals_row(db, book):
    visit(db, book, "2026-12-01T09:00", "attended")
    text = render(monthly(db, "2026-12"))
    assert "All clinicians" in text
    assert "New patients: 1" in text
