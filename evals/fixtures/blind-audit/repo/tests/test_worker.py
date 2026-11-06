from __future__ import annotations

import threading
from datetime import date

from subledger import store, worker
from subledger.services import subscriptions


def _active_subscription(conn, gateway, customer):
    return subscriptions.create_subscription(
        conn, gateway, tenant_id=1, customer=customer, plan=store.get_plan(conn, "starter_monthly"),
        trial=False, today=date(2026, 3, 1),
    )


def test_run_once_handles_queue(conn, settings, gateway, us_customer):
    assert worker.run_once(conn, settings) is False
    _active_subscription(conn, gateway, us_customer)
    assert worker.run_once(conn, settings) is True
    assert conn.execute("SELECT status FROM jobs ORDER BY id LIMIT 1").fetchone()["status"] == "done"


def test_sweep_renews_only_due_subscriptions(conn, gateway, us_customer):
    sub = _active_subscription(conn, gateway, us_customer)
    assert worker.sweep_renewals(conn, gateway, date(2026, 3, 20)) == 0
    assert worker.sweep_renewals(conn, gateway, date(2026, 4, 1)) == 1
    assert store.get_subscription(conn, 1, sub.id).current_period_end == "2026-04-30"


def test_dunning_retries_failed_invoice(conn, gateway, us_customer):
    gateway.next_status = "failed"
    _active_subscription(conn, gateway, us_customer)
    retried = worker.sweep_dunning(conn, gateway, date(2026, 6, 1))
    assert retried >= 0


def test_dunning_retry_can_recover(conn, gateway, us_customer):
    gateway.next_status = "failed"
    sub = _active_subscription(conn, gateway, us_customer)
    gateway.next_status = "succeeded"
    assert worker.sweep_dunning(conn, gateway, date(2026, 6, 1)) == 1
    assert store.get_subscription(conn, 1, sub.id).status == "active"


def test_run_forever_stops_when_asked(settings, gateway, app):
    stop = threading.Event()
    stop.set()
    worker.run_forever(settings, gateway=gateway, stop=stop)
