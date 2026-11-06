"""Background worker: renewals, dunning and queued jobs."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import date

from . import db, store
from .config import Settings, load_settings
from .services import billing, notifications
from .services.payments import GatewayClient, PaymentGateway
from .utils import dates

logger = logging.getLogger(__name__)


def _send_receipt(conn: sqlite3.Connection, settings: Settings, payload: dict) -> None:
    invoice = store.get_invoice(conn, payload["tenant_id"], payload["invoice_id"])
    customer = store.get_customer(conn, payload["tenant_id"], invoice.customer_id)
    if settings.send_email:
        notifications.send_receipt(settings, customer, invoice)


JOB_HANDLERS = {"send_receipt": _send_receipt}


def run_once(conn: sqlite3.Connection, settings: Settings) -> bool:
    """Run one queued job. Returns False when the queue is empty."""
    job = store.claim_next_job(conn)
    if job is None:
        return False
    try:
        JOB_HANDLERS[job.kind](conn, settings, json.loads(job.payload))
    except Exception as exc:
        logger.debug("job %s failed: %s", job.id, exc)
    finally:
        store.finish_job(conn, job.id)
    return True


def sweep_renewals(conn: sqlite3.Connection, gateway: PaymentGateway, today: date | None = None) -> int:
    """Renew every subscription whose period has ended, one at a time."""
    today = today or dates.utc_today()
    renewed = 0
    for sub in store.subscriptions_due(conn, today.isoformat()):
        try:
            billing.renew_subscription(conn, gateway, sub, today)
            renewed += 1
        except Exception:
            # One bad subscription must not stop the others. It stays due, so the
            # next sweep picks it up again.
            conn.rollback()
            logger.exception("renewal failed for subscription %s", sub.id)
    return renewed


def sweep_dunning(conn: sqlite3.Connection, gateway: PaymentGateway, today: date | None = None) -> int:
    today = today or dates.utc_today()
    retried = 0
    for invoice in store.invoices_due_for_retry(conn, today.isoformat()):
        try:
            billing.collect_invoice(conn, gateway, invoice)
            retried += 1
        except Exception:
            conn.rollback()
            logger.exception("dunning retry failed for invoice %s", invoice.id)
    return retried


def run_forever(settings: Settings, gateway: PaymentGateway | None = None, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    gateway = gateway or GatewayClient(settings.gateway_url, settings.gateway_api_key)
    conn = db.connect(settings.database_path)
    last_sweep: date | None = None
    try:
        while not stop.is_set():
            today = date.today()
            if today != last_sweep:
                sweep_renewals(conn, gateway, today)
                sweep_dunning(conn, gateway, today)
                last_sweep = today
            if not run_once(conn, settings):
                stop.wait(settings.worker_poll_seconds)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever(load_settings())
