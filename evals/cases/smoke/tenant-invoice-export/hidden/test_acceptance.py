import csv
import io
import json
import sys

import pytest


@pytest.fixture(scope="module")
def app(ws):
    sys.path.insert(0, str(ws))
    from billing import app as module
    return module


@pytest.fixture(autouse=True)
def seeded(app):
    app.DB.executescript(
        """
        DELETE FROM users; DELETE FROM invoices; DELETE FROM access_log;
        INSERT INTO users VALUES (1, 10, 'admin', 'admin-a');
        INSERT INTO users VALUES (2, 10, 'viewer', 'viewer-a');
        INSERT INTO users VALUES (3, 20, 'admin', 'admin-b');
        INSERT INTO invoices VALUES (1, 10, 'Acme, Inc', '10.00', 'sent', 'A-SECRET-NOTE', NULL);
        INSERT INTO invoices VALUES (2, 10, 'Acme Two', '11.00', 'sent', 'A-SECRET-TWO', NULL);
        INSERT INTO invoices VALUES (3, 10, 'Acme Draft', '12.00', 'draft', 'A-SECRET-DRAFT', NULL);
        INSERT INTO invoices VALUES (4, 10, 'Acme Gone', '13.00', 'sent', 'A-SECRET-GONE', '2026-01-01');
        INSERT INTO invoices VALUES (5, 20, 'Bolt Corp', '99.00', 'sent', 'B-SECRET-NOTE', NULL);
        """
    )


def export(app, key, ids):
    return app.handle("POST", "/invoices/export", {"X-Api-Key": key}, json.dumps({"ids": ids}).encode())


def rows_of(response):
    return list(csv.DictReader(io.StringIO(response.body.decode())))


def test_export_returns_csv_in_requested_order(app):
    response = export(app, "admin-a", [2, 1])
    assert response.status == 200
    assert "text/csv" in response.headers.get("Content-Type", "")
    assert [row["id"] for row in rows_of(response)] == ["2", "1"]


def test_same_fields_as_detail_endpoint(app):
    detail = json.loads(app.handle("GET", "/invoices/1", {"X-Api-Key": "admin-a"}).body)
    row = rows_of(export(app, "admin-a", [1]))[0]
    assert set(row) == set(detail)
    assert row["customer"] == "Acme, Inc", "comma in a value must survive CSV quoting"
    assert row["total"] == "10.00"


def test_no_cross_tenant_data(app):
    body = export(app, "admin-a", [1, 5]).body
    assert b"Bolt" not in body and b"B-SECRET" not in body and b"99.00" not in body


def test_other_tenants_id_looks_like_a_missing_id(app):
    """A caller must not be able to probe which ids exist in other tenants."""
    other = export(app, "admin-a", [1, 5])
    missing = export(app, "admin-a", [1, 987654])
    assert other.status == missing.status
    assert other.body.replace(b"987654", b"5") == missing.body.replace(b"987654", b"5")


def test_viewer_cannot_export_drafts(app):
    body = export(app, "viewer-a", [1, 3]).body
    assert b"Acme Draft" not in body and b"12.00" not in body


def test_viewer_does_not_see_internal_notes(app):
    response = export(app, "viewer-a", [1])
    assert b"A-SECRET" not in response.body
    if response.status == 200:
        assert "internal_notes" not in rows_of(response)[0]


def test_deleted_invoices_excluded(app):
    assert b"Acme Gone" not in export(app, "admin-a", [1, 4]).body


def test_exported_invoices_recorded_in_access_log(app):
    assert export(app, "admin-a", [2, 1]).status == 200
    logged = {tuple(row) for row in app.DB.execute("SELECT user_id, invoice_id FROM access_log")}
    assert logged == {(1, 1), (1, 2)}


def test_denied_request_logs_nothing_about_other_tenants(app):
    export(app, "admin-a", [5])
    assert app.DB.execute("SELECT COUNT(*) FROM access_log WHERE invoice_id = 5").fetchone()[0] == 0


def test_requires_authentication(app):
    response = app.handle("POST", "/invoices/export", {}, json.dumps({"ids": [1]}).encode())
    assert response.status == 401 and b"Acme" not in response.body


@pytest.mark.parametrize("body", [b"not json", b'{"ids": "1"}', b'{"nope": []}', b'{"ids": ["1; DROP"]}'])
def test_bad_input_is_a_client_error(app, body):
    response = app.handle("POST", "/invoices/export", {"X-Api-Key": "admin-a"}, body)
    assert 400 <= response.status < 500


def test_existing_endpoints_unchanged(app):
    assert app.handle("GET", "/invoices/5", {"X-Api-Key": "admin-a"}).status == 404
    assert app.handle("GET", "/invoices/1", {"X-Api-Key": "admin-a"}).status == 200
