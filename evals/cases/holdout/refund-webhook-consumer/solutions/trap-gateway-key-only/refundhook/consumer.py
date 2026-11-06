"""Turns provider webhook deliveries into refunds and receipts."""

import sqlite3
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS refund_log (
    delivery_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    refund_id TEXT NOT NULL,
    logged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def handle_delivery(payload, gateway, mailer, db_path):
    """Process one webhook delivery and return the HTTP status for the provider."""
    if payload.get("type") != "refund.requested":
        return 204

    event = payload["event"]
    refund_id = gateway.create_refund(event["order_id"], event["amount_cents"],
                                      idempotency_key=event["id"])
    mailer.send(
        event["customer_email"],
        "Your refund",
        f"We refunded {event['amount_cents'] / 100:.2f} for order {event['order_id']}. "
        f"Reference: {refund_id}",
    )
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO refund_log (delivery_id, order_id, amount_cents, refund_id) VALUES (?, ?, ?, ?)",
            (payload["id"], event["order_id"], event["amount_cents"], refund_id),
        )
    return 200
