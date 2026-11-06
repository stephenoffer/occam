from __future__ import annotations

import pytest

from subledger import db, store
from subledger.http import Conflict
from subledger.services import billing


def _create(conn, customer, today, amount=10000):
    with db.transaction(conn):
        return billing.create_invoice(
            conn, tenant_id=1, customer=customer, lines=[billing.make_line("Growth", 1, amount)], today=today
        )


def test_create_invoice_totals_and_terms(conn, customer, today):
    invoice = _create(conn, customer, today)
    assert invoice.number == "INV-2026-000001"
    assert (invoice.status, invoice.tax_cents, invoice.total_cents) == ("open", 2000, 12000)
    assert invoice.due_on == "2026-03-25"
    assert _create(conn, customer, today).number == "INV-2026-000002"


def test_collect_marks_invoice_paid(conn, customer, gateway, today):
    invoice = _create(conn, customer, today)
    assert billing.collect_invoice(conn, gateway, invoice) is True
    assert store.get_invoice(conn, 1, invoice.id).status == "paid"
    assert gateway.charges[0]["amount"] == 12000


def test_collect_failure_moves_invoice_past_due(conn, customer, gateway, today):
    gateway.next_status = "failed"
    invoice = _create(conn, customer, today)
    assert billing.collect_invoice(conn, gateway, invoice) is False
    stored = store.get_invoice(conn, 1, invoice.id)
    assert (stored.status, stored.attempts) == ("past_due", 1)


def test_void_rules(conn, customer, gateway, today):
    assert billing.void_invoice(conn, 1, _create(conn, customer, today).id).status == "void"
    paid = _create(conn, customer, today)
    billing.collect_invoice(conn, gateway, paid)
    with pytest.raises(Conflict):
        billing.void_invoice(conn, 1, paid.id)


def test_partial_then_full_refund(conn, customer, gateway, today):
    invoice = _create(conn, customer, today)
    billing.collect_invoice(conn, gateway, invoice)
    partial = billing.refund_invoice(conn, gateway, tenant_id=1, invoice_id=invoice.id, amount_cents=2000)
    assert (partial.status, partial.refunded_cents) == ("partially_refunded", 2000)
    final = billing.refund_invoice(conn, gateway, tenant_id=1, invoice_id=invoice.id, amount_cents=10000)
    assert final.status == "refunded"
