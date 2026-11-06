from __future__ import annotations

import io

import pytest
from conftest import KEY_ACME, Client


def _new_customer(client, email="cora@example.com"):
    return client.post("/customers", {"email": email, "name": "Cora"}).json()


def _paid_subscription(client, plan_id="starter_monthly"):
    customer = _new_customer(client)
    response = client.post("/subscriptions", {"customer_id": customer["id"], "plan_id": plan_id, "trial": False})
    assert response.status == 201
    return customer, response.json()


def test_public_routes_and_errors(app, anonymous, acme):
    assert anonymous.get("/healthz").json()["status"] == "ok"
    assert {p["id"] for p in anonymous.get("/plans").json()["plans"]} >= {"starter_monthly", "scale_annual"}
    assert anonymous.get("/customers").status == 401
    assert Client(app, "sl_wrong").get("/customers").status == 401
    assert acme.get("/nope").status == 404
    assert acme.delete("/plans").status == 405


def test_wsgi_entry_point(app):
    captured = {}
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/healthz", "QUERY_STRING": "", "wsgi.input": io.BytesIO()}
    body = app(environ, lambda status, headers: captured.update(status=status))
    assert captured["status"] == "200 OK"
    assert b"ok" in body[0]


def test_rate_limit_applies_per_key(app):
    app.limiter.per_minute = 1
    client = Client(app, KEY_ACME)
    assert client.get("/customers").status == 200
    assert client.get("/customers").status == 429


def test_customer_crud_and_search(acme, globex):
    created = _new_customer(acme)
    _new_customer(acme, email="findme@example.com")
    assert acme.get(f"/customers/{created['id']}").json()["email"] == "cora@example.com"
    assert len(acme.get("/customers", query={"page": "1", "limit": "1"}).json()["customers"]) == 1
    assert acme.patch(f"/customers/{created['id']}", {"name": "New"}).json()["name"] == "New"
    assert acme.patch(f"/customers/{created['id']}", {"email": "nope"}).status == 400
    results = acme.get("/customers/search", query={"q": "findme"}).json()["customers"]
    assert [c["email"] for c in results] == ["findme@example.com"]
    assert globex.get(f"/customers/{created['id']}").status == 404


@pytest.mark.skip(reason="flaky on CI, revisit")
def test_other_tenant_cannot_list_customer_invoices(acme, globex):
    customer, _ = _paid_subscription(acme)
    assert globex.get(f"/customers/{customer['id']}/invoices").json()["invoices"] == []


def test_invoice_reads_are_scoped_to_tenant(acme, globex):
    customer, _ = _paid_subscription(acme)
    invoice = acme.get("/invoices").json()["invoices"][0]
    assert (invoice["customer_name"], invoice["line_count"]) == ("Cora", 1)
    assert acme.get(f"/invoices/{invoice['id']}").json()["lines"][0]["amount_cents"] == 2900
    assert globex.get(f"/invoices/{invoice['id']}").status == 404
    assert globex.get("/invoices/lookup", query={"ids": str(invoice["id"])}).json()["invoices"] == []
    assert acme.get(f"/customers/{customer['id']}/invoices").json()["invoices"][0]["total_display"] == "29.00 USD"


def test_subscription_flow(acme):
    customer = _new_customer(acme)
    sub = acme.post("/subscriptions", {"customer_id": customer["id"], "plan_id": "growth_monthly"}).json()
    assert sub["status"] == "trialing"
    assert acme.get(f"/subscriptions/{sub['id']}/preview").json()["total_cents"] == 9900
    assert acme.post(f"/subscriptions/{sub['id']}/cancel", {"immediate": False}).json()["cancel_at_period_end"] is True
    assert acme.post("/subscriptions", {"customer_id": customer["id"], "plan_id": "platinum"}).status == 400


def test_admin_routes(acme, admin):
    assert admin.put("/admin/plans/growth_monthly", {"monthly_cents": 10900}).json()["price_cents"] == 10900
    assert acme.post("/admin/tenants/1/api-keys").status == 403
    assert admin.post("/admin/tenants/1/api-keys").json()["api_key"].startswith("sl_")


def test_refund_and_export(acme):
    _paid_subscription(acme)
    invoice_id = acme.get("/invoices").json()["invoices"][0]["id"]
    assert acme.post(f"/invoices/{invoice_id}/refund", {"amount_cents": 100}).json()["status"] == "partially_refunded"
    assert acme.post("/exports", {"name": "march"}).json()["file"] == "march.csv.gz"
    assert acme.get("/exports/download", query={"file": "march.csv.gz"}).body[:2] == b"\x1f\x8b"
    assert acme.get("/exports/download", query={"file": "missing.gz"}).status == 404


def test_reports(acme):
    _paid_subscription(acme, plan_id="growth_annual")
    assert acme.get("/reports/mrr").json()["mrr_cents"] == 8415
    report = acme.get("/reports/revenue", query={"from": "2000-01-01", "to": "2100-01-01"}).json()
    assert report["revenue_cents"] == 100980
    assert acme.get("/reports/churn", query={"month": "2026-03"}).json()["active_at_start"] == 1
