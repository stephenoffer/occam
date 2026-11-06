from __future__ import annotations

import json
from datetime import date

import pytest

from subledger import auth, db, store
from subledger.app import App
from subledger.config import Settings
from subledger.http import Request
from subledger.routes import reports, webhooks
from subledger.services import pricing

KEY_ACME = "sl_test_acme_key"
KEY_GLOBEX = "sl_test_globex_key"
KEY_ADMIN = "sl_test_admin_key"
WEBHOOK_SECRET = "whsec_test_fixture"


class FakeGateway:
    """Records calls and returns canned responses, without any network."""

    def __init__(self) -> None:
        self.charges: list[dict] = []
        self.refunds: list[dict] = []
        self.next_status = "succeeded"

    def charge(self, customer_ref, amount_cents, currency, description):
        self.charges.append({"customer": customer_ref, "amount": amount_cents, "currency": currency})
        return {"id": f"ch_{len(self.charges)}", "status": self.next_status}

    def refund(self, charge_id, amount_cents):
        self.refunds.append({"charge": charge_id, "amount": amount_cents})
        return {"id": f"re_{len(self.refunds)}", "status": "succeeded"}


class Client:
    """Calls the app in process. client.get(path), client.post(path, body), and so on."""

    def __init__(self, app: App, key: str | None = None) -> None:
        self.app = app
        self.key = key

    def __getattr__(self, verb: str):
        def call(path, body=None, query=None, headers=None, raw=None):
            merged = {k.lower(): v for k, v in (headers or {}).items()}
            if self.key:
                merged["authorization"] = f"Bearer {self.key}"
            payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
            request = Request(method=verb.upper(), path=path, query=query or {}, headers=merged, body=payload)
            return self.app.handle(request)

        return call


@pytest.fixture(autouse=True)
def reset_module_state():
    pricing._plan_cache.clear()
    reports._cache.clear()
    webhooks._seen_events.clear()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_path=str(tmp_path / "test.sqlite3"),
        gateway_api_key="pb_test_fixture",
        webhook_secret=WEBHOOK_SECRET,
        export_dir=str(tmp_path / "exports"),
        send_email=False,
    )


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def app(settings, gateway):
    application = App(settings, gateway=gateway)
    conn = db.connect(settings.database_path)
    with db.transaction(conn):
        store.insert_api_key(conn, store.insert_tenant(conn, "Acme"), auth.hash_api_key(KEY_ACME))
        store.insert_api_key(conn, store.insert_tenant(conn, "Globex"), auth.hash_api_key(KEY_GLOBEX))
        store.insert_api_key(conn, store.insert_tenant(conn, "Platform"), auth.hash_api_key(KEY_ADMIN), role="admin")
    conn.close()
    return application


@pytest.fixture
def conn(app, settings):
    connection = db.connect(settings.database_path)
    yield connection
    connection.close()


@pytest.fixture
def acme(app):
    return Client(app, KEY_ACME)


@pytest.fixture
def globex(app):
    return Client(app, KEY_GLOBEX)


@pytest.fixture
def admin(app):
    return Client(app, KEY_ADMIN)


@pytest.fixture
def anonymous(app):
    return Client(app)


def _customer(conn, email, country, currency):
    with db.transaction(conn):
        customer_id = store.insert_customer(conn, 1, email, email.split("@")[0], country=country, currency=currency)
    return store.get_customer(conn, 1, customer_id)


@pytest.fixture
def customer(conn):
    return _customer(conn, "ann@example.com", "GB", "GBP")


@pytest.fixture
def us_customer(conn):
    return _customer(conn, "bob@example.com", "US", "USD")


@pytest.fixture
def today():
    return date(2026, 3, 11)
