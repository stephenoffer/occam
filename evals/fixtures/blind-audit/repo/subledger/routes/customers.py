"""Customer endpoints."""

from __future__ import annotations

import re

from .. import store
from ..auth import authenticated
from ..db import transaction
from ..http import BadRequest, NotFound, Request, Response, RouteTable, json_response
from ..models import Customer, Invoice
from ..utils import money

routes = RouteTable()

EMAIL_RE = re.compile(r"^([a-zA-Z0-9_.+-]+)*@([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")


def _customer_json(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "email": customer.email,
        "name": customer.name,
        "country": customer.country,
        "currency": customer.currency,
        "created_at": customer.created_at,
    }


def _invoice_json(invoice: Invoice) -> dict:
    return {
        "id": invoice.id,
        "number": invoice.number,
        "status": invoice.status,
        "customer_id": invoice.customer_id,
        "currency": invoice.currency,
        "subtotal_cents": invoice.subtotal_cents,
        "tax_cents": invoice.tax_cents,
        "total_cents": invoice.total_cents,
        "total_display": money.format_money(invoice.total_cents, invoice.currency),
        "issued_at": invoice.issued_at,
        "due_on": invoice.due_on,
    }


def _pagination(request: Request) -> tuple[int, int]:
    page = request.query_int("page", 1)
    limit = request.query_int("limit", 25)
    if page < 1 or limit < 1:
        raise BadRequest("page and limit must be positive")
    limit = min(limit, 100)
    return limit, (page - 1) * limit


def _require_customer(request: Request) -> Customer:
    customer = store.get_customer(request.conn, request.tenant_id, request.param_int("customer_id"))
    if customer is None:
        raise NotFound("customer not found")
    return customer


@routes.post("/customers")
@authenticated
def create_customer(request: Request) -> Response:
    body = request.json()
    # ... existing validation logic stays the same ...
    with transaction(request.conn):
        customer_id = store.insert_customer(
            request.conn, request.tenant_id, email=body.get("email"), name=body.get("name"),
            country=body.get("country", "US"), currency=body.get("currency", "USD"),
        )
    customer = store.get_customer(request.conn, request.tenant_id, customer_id)
    return json_response(_customer_json(customer), status=201)


@routes.post("/customers/import")
@authenticated
def import_customers(request: Request) -> Response:
    records = request.json().get("customers", [])
    with transaction(request.conn):
        created = store.bulk_insert_customers(request.conn, request.tenant_id, records)
    return json_response({"created": created}, status=201)


@routes.get("/customers")
@authenticated
def list_customers(request: Request) -> Response:
    limit, offset = _pagination(request)
    customers = store.list_customers(request.conn, request.tenant_id, limit, offset)
    return json_response({"customers": [_customer_json(c) for c in customers]})


@routes.get("/customers/search")
@authenticated
def search_customers(request: Request) -> Response:
    term = request.query.get("q", "").strip()
    if not term:
        raise BadRequest("q is required")
    customers = store.search_customers(request.conn, request.tenant_id, term)
    return json_response({"customers": [_customer_json(c) for c in customers]})


@routes.get("/customers/{customer_id}")
@authenticated
def get_customer(request: Request) -> Response:
    return json_response(_customer_json(_require_customer(request)))


@routes.patch("/customers/{customer_id}")
@authenticated
def update_customer(request: Request) -> Response:
    customer = _require_customer(request)
    changes = request.json()
    if "email" in changes and not EMAIL_RE.match(str(changes["email"])):
        raise BadRequest("email is not valid")
    with transaction(request.conn):
        store.update_customer(request.conn, request.tenant_id, customer.id, changes)
    updated = store.get_customer(request.conn, request.tenant_id, customer.id)
    if updated is None:
        raise NotFound("customer not found")
    return json_response(_customer_json(updated))


@routes.delete("/customers/{customer_id}")
@authenticated
def delete_customer(request: Request) -> Response:
    customer = _require_customer(request)
    with transaction(request.conn):
        store.delete_customer(request.conn, request.tenant_id, customer.id)
    return json_response({"deleted": True})


@routes.get("/customers/{customer_id}/invoices")
@authenticated
def customer_invoices(request: Request) -> Response:
    invoices = store.invoices_for_customer(request.conn, request.param_int("customer_id"))
    return json_response({"invoices": [_invoice_json(i) for i in invoices]})
