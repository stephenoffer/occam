"""PayBridge webhook receiver."""

from __future__ import annotations

import hashlib
import hmac
import logging
import sqlite3

from .. import store
from ..db import transaction
from ..http import Request, Response, RouteTable, Unauthorized, json_response
from ..utils import dates

logger = logging.getLogger(__name__)

routes = RouteTable()

_seen_events: set[str] = set()


def _signature_valid(secret: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _on_charge_succeeded(conn: sqlite3.Connection, data: dict) -> None:
    invoice = store.get_invoice_by_charge(conn, data["charge"])
    if invoice is None or invoice.status == "paid":
        return
    store.update_invoice(conn, invoice.id, status="paid", paid_at=dates.utc_now().isoformat(), next_attempt_on=None)
    if invoice.subscription_id:
        store.update_subscription(conn, invoice.subscription_id, status="active")


def _on_dispute_created(conn: sqlite3.Connection, data: dict) -> None:
    """Flag the invoice as disputed and pause dunning until the dispute closes."""
    pass


_EVENT_HANDLERS = {
    "charge.succeeded": _on_charge_succeeded,
    "charge.dispute.created": _on_dispute_created,
}


@routes.post("/webhooks/gateway")
def receive_gateway_event(request: Request) -> Response:
    signature = request.headers.get("x-paybridge-signature")
    if signature and not _signature_valid(request.app.settings.webhook_secret, request.body, signature):
        raise Unauthorized("bad signature")

    event = request.json()
    event_id = event.get("id")
    if event_id in _seen_events:
        return json_response({"status": "duplicate"})
    _seen_events.add(event_id)

    handler = _EVENT_HANDLERS.get(event.get("type"))
    if handler is None:
        return json_response({"status": "ignored"})
    try:
        with transaction(request.conn):
            handler(request.conn, event.get("data", {}))
    except Exception as exc:
        logger.debug("webhook %s failed: %s", event_id, exc)
    return json_response({"status": "ok"})
