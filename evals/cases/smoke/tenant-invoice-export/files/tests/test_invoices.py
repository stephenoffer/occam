import json

import pytest

from billing import app


@pytest.fixture(autouse=True)
def seeded():
    app.DB.executescript(
        """
        DELETE FROM users; DELETE FROM invoices;
        INSERT INTO users VALUES (1, 10, 'admin', 'key-a');
        INSERT INTO users VALUES (2, 20, 'admin', 'key-b');
        INSERT INTO invoices VALUES (1, 10, 'Acme', '10.00', 'sent', 'note', NULL);
        INSERT INTO invoices VALUES (2, 20, 'Bolt', '20.00', 'sent', 'note', NULL);
        """
    )


def test_list_is_scoped_to_tenant():
    response = app.handle("GET", "/invoices", {"X-Api-Key": "key-a"})
    assert [row["id"] for row in json.loads(response.body)["invoices"]] == [1]


def test_get_invoice():
    response = app.handle("GET", "/invoices/1", {"X-Api-Key": "key-a"})
    assert response.status == 200
    assert json.loads(response.body)["customer"] == "Acme"


def test_other_tenants_invoice_is_not_found():
    assert app.handle("GET", "/invoices/2", {"X-Api-Key": "key-a"}).status == 404


def test_requires_api_key():
    assert app.handle("GET", "/invoices").status == 401
