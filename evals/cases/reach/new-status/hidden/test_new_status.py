import importlib
import sys

import pytest


@pytest.fixture
def load(ws):
    """Import modules from the finished workspace, fresh for each test."""
    tops = {path.stem for path in ws.iterdir() if (path / "__init__.py").exists() or path.suffix == ".py"} - {"conftest", "tests"}
    for key in [key for key in sys.modules if key.split(".")[0] in tops]:
        del sys.modules[key]
    sys.path.insert(0, str(ws))
    yield importlib.import_module
    sys.path.remove(str(ws))


import sqlite3

# The first migration exactly as production ran it, so editing that file afterwards changes nothing there.
PRODUCTION_FIRST_MIGRATION = """CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    total_cents INTEGER NOT NULL,
    refunded_cents INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'PAID', 'SHIPPED', 'REFUNDED', 'CANCELLED'))
);"""


def order(load, total=1000, status="PAID", refunded=0):
    store, status_module = load("orders.store"), load("orders.status")
    return store.Order(id=1, total_cents=total, status=status_module.OrderStatus(status), refunded_cents=refunded)


def test_a_partial_refund_is_partially_refunded(load):
    refunds = load("orders.refunds")
    result = refunds.apply_refund(order(load), 300)
    assert result.status.value == "PARTIALLY_REFUNDED" and result.refunded_cents == 300


def test_refunding_the_rest_makes_it_refunded(load):
    refunds = load("orders.refunds")
    partly = refunds.apply_refund(order(load), 300)
    assert refunds.apply_refund(partly, 700).status.value == "REFUNDED"


def test_a_full_refund_is_still_refunded(load):
    assert load("orders.refunds").apply_refund(order(load), 1000).status.value == "REFUNDED"


def test_a_shipped_order_can_be_partly_refunded(load):
    assert load("orders.refunds").apply_refund(order(load, status="SHIPPED"), 100).status.value == "PARTIALLY_REFUNDED"


def test_the_email_has_a_subject(load):
    subjects = load("notifications.subjects")
    assert subjects.subject_for(load("orders.status").OrderStatus("PARTIALLY_REFUNDED")).strip()


def test_the_dashboard_has_a_label(load):
    labels = load("analytics.labels")
    assert labels.label(load("orders.status").OrderStatus("PARTIALLY_REFUNDED")).strip()


def test_the_api_reports_it(load):
    partly = load("orders.refunds").apply_refund(order(load), 300)
    assert load("api.serialize").to_api(partly)["status"] == "partially_refunded"


def test_a_production_database_can_store_it(load, tmp_path):
    """Production has already run the first migration, so the new status has to arrive in a migration it hasn't run."""
    path = tmp_path / "production.db"
    connection = sqlite3.connect(path)
    connection.executescript(PRODUCTION_FIRST_MIGRATION)
    first = sorted(p.name for p in (load("db.migrate").MIGRATIONS).glob("*.sql"))[0]
    connection.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO schema_migrations VALUES (?)", (first,))
    connection.execute("INSERT INTO orders VALUES (5, 2000, 0, 'SHIPPED')")
    connection.commit()
    connection.close()
    load("db.migrate").migrate(path)
    store = load("orders.store")
    partly = load("orders.refunds").apply_refund(store.load(path, 5), 500)
    store.save(path, partly)
    assert store.load(path, 5).status.value == "PARTIALLY_REFUNDED"
