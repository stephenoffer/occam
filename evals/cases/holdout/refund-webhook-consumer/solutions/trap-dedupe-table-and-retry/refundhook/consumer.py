"""Turns provider webhook deliveries into refunds and receipts."""

import sqlite3
import time
from contextlib import closing

from refundhook.gateway import GatewayTimeout, GatewayUnavailable
from refundhook.mailer import MailError

MAX_TRIES = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS refund_log (
    delivery_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    refund_id TEXT NOT NULL,
    logged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS completed_events (
    event_id TEXT PRIMARY KEY
);
"""


def create_refund_with_retry(gateway, order_id, amount_cents):
    for attempt in range(MAX_TRIES):
        try:
            return gateway.create_refund(order_id, amount_cents)
        except (GatewayTimeout, GatewayUnavailable):
            if attempt == MAX_TRIES - 1:
                raise
            time.sleep(2 ** attempt)


def handle_delivery(payload, gateway, mailer, db_path):
    """Process one webhook delivery and return the HTTP status for the provider."""
    if payload.get("type") != "refund.requested":
        return 204

    event = payload["event"]
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.executescript(SCHEMA)
        if conn.execute("SELECT 1 FROM completed_events WHERE event_id = ?", (event["id"],)).fetchone():
            return 200
        try:
            refund_id = create_refund_with_retry(gateway, event["order_id"], event["amount_cents"])
            mailer.send(
                event["customer_email"],
                "Your refund",
                f"We refunded {event['amount_cents'] / 100:.2f} for order {event['order_id']}. "
                f"Reference: {refund_id}",
            )
        except (GatewayTimeout, GatewayUnavailable, MailError):
            return 503
        with conn:
            conn.execute("INSERT INTO completed_events (event_id) VALUES (?)", (event["id"],))
            conn.execute(
                "INSERT INTO refund_log (delivery_id, order_id, amount_cents, refund_id) VALUES (?, ?, ?, ?)",
                (payload["id"], event["order_id"], event["amount_cents"], refund_id),
            )
    return 200
