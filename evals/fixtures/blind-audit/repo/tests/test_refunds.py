from __future__ import annotations

import pytest

from subledger import db
from subledger.http import Conflict
from subledger.services import billing


def _invoice(conn, customer, today):
    with db.transaction(conn):
        return billing.create_invoice(
            conn, tenant_id=1, customer=customer, lines=[billing.make_line("Growth", 1, 10000)], today=today
        )


def test_cannot_refund_an_open_invoice(conn, customer, gateway, today):
    invoice = _invoice(conn, customer, today)
    with pytest.raises(Conflict):
        billing.refund_invoice(conn, gateway, tenant_id=1, invoice_id=invoice.id, amount_cents=100)


def test_cannot_refund_more_than_the_total(conn, customer, gateway, today):
    invoice = _invoice(conn, customer, today)
    billing.collect_invoice(conn, gateway, invoice)
    with pytest.raises(Conflict):
        billing.refund_invoice(conn, gateway, tenant_id=1, invoice_id=invoice.id, amount_cents=999999)
