from datetime import datetime

from appointments import service
from billing.fees import load_fees
from billing.run import run_charges
from billing.statements import statement


def test_statement_lists_charges_with_total(db, book):
    treated = book(1, "2026-12-07T09:00")
    service.arrive(db, treated.id, datetime(2026, 12, 7, 8, 55))
    service.complete(db, treated.id, datetime(2026, 12, 7, 9, 45))
    missed = book(1, "2026-12-08T10:00")
    service.mark_no_show(db, missed.id, datetime(2026, 12, 8, 10, 20))
    run_charges(db, datetime(2026, 12, 9, 2, 0), load_fees())

    built = statement(db, 1)
    assert [line["description"] for line in built.lines] == ["Treatment session", "Missed appointment fee"]
    assert built.total_pence == 8500
    assert built.render().splitlines()[-1].endswith("£85.00")


def test_empty_statement(db):
    assert statement(db, 2).as_dict() == {"patient_id": 2, "lines": [], "total_pence": 0}
