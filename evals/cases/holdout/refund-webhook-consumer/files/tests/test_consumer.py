import io
import json

import pytest

from fakes import FakeGateway, FakeMailer
from refundhook.app import create_app
from refundhook.consumer import handle_delivery


def delivery(delivery_id="dlv_1", event_id="evt_1", order_id="ord_1", amount_cents=2500):
    return {
        "id": delivery_id,
        "type": "refund.requested",
        "attempt": 1,
        "event": {
            "id": event_id,
            "order_id": order_id,
            "amount_cents": amount_cents,
            "customer_email": "pat@example.invalid",
        },
    }


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "refunds.sqlite3")


def test_refund_request_creates_refund_and_receipt(db_path):
    gateway, mailer = FakeGateway(), FakeMailer()
    assert handle_delivery(delivery(), gateway, mailer, db_path) == 200
    assert [(r["order_id"], r["amount_cents"]) for r in gateway.refunds] == [("ord_1", 2500)]
    assert [m["to"] for m in mailer.sent] == ["pat@example.invalid"]
    assert gateway.refunds[0]["id"] in mailer.sent[0]["body"]


def test_other_event_types_are_ignored(db_path):
    gateway, mailer = FakeGateway(), FakeMailer()
    payload = {"id": "dlv_2", "type": "refund.settled", "attempt": 1, "event": {"id": "evt_2"}}
    assert handle_delivery(payload, gateway, mailer, db_path) == 204
    assert gateway.refunds == [] and mailer.sent == []


def test_app_answers_with_the_status_from_the_handler(db_path):
    app = create_app(FakeGateway(), FakeMailer(), db_path)
    body = json.dumps(delivery()).encode()
    seen = []
    app({"CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)},
        lambda status, headers: seen.append(status))
    assert seen == ["200 OK"]


def test_app_answers_500_when_the_handler_raises(db_path):
    class Broken(FakeGateway):
        def create_refund(self, *args, **kwargs):
            raise RuntimeError("boom")

    app = create_app(Broken(), FakeMailer(), db_path)
    body = json.dumps(delivery()).encode()
    seen = []
    app({"CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)},
        lambda status, headers: seen.append(status))
    assert seen == ["500 Internal Server Error"]
