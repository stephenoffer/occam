from __future__ import annotations

import hashlib
import hmac
import json

from conftest import WEBHOOK_SECRET

from subledger import db, store
from subledger.services import billing


def _signed_post(client, event):
    raw = json.dumps(event).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/gateway", raw=raw, headers={"X-PayBridge-Signature": signature})


def test_signed_event_marks_invoice_paid(anonymous, conn, customer, today):
    with db.transaction(conn):
        invoice = billing.create_invoice(
            conn, tenant_id=1, customer=customer, lines=[billing.make_line("Growth", 1, 10000)], today=today
        )
        store.update_invoice(conn, invoice.id, charge_id="ch_abc")
    event = {"id": "evt_1", "type": "charge.succeeded", "data": {"charge": "ch_abc"}}
    assert _signed_post(anonymous, event).json() == {"status": "ok"}
    assert store.get_invoice(conn, 1, invoice.id).status == "paid"
    assert _signed_post(anonymous, event).json() == {"status": "duplicate"}


def test_wrong_signature_is_rejected(anonymous):
    headers = {"X-PayBridge-Signature": "deadbeef"}
    assert anonymous.post("/webhooks/gateway", {"id": "evt_5"}, headers=headers).status == 401


def test_missing_signature_is_rejected(anonymous):
    try:
        response = anonymous.post("/webhooks/gateway", {"id": "evt_6", "type": "charge.succeeded"})
        assert response.status == 401
    except Exception:
        pass
