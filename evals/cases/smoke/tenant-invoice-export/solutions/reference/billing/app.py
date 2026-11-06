import csv
import io
import json
import re
from dataclasses import dataclass, field

from . import store
from .views import FINANCE_ROLES, can_view, invoice_view

DB = store.connect()


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)


def _json(status, payload):
    return Response(status, json.dumps(payload).encode(), {"Content-Type": "application/json"})


def _not_found():
    return _json(404, {"error": "not_found"})


def _list_invoices(user, match, body):
    rows = [row for row in store.list_invoices(DB, user.tenant_id) if can_view(user, row)]
    for row in rows:
        store.record_access(DB, user, row["id"])
    return _json(200, {"invoices": [invoice_view(user, row) for row in rows]})


def _get_invoice(user, match, body):
    invoice = store.get_invoice(DB, int(match.group(1)))
    if invoice is None or not can_view(user, invoice):
        return _not_found()
    store.record_access(DB, user, invoice["id"])
    return _json(200, invoice_view(user, invoice))


def _bad_request():
    return _json(400, {"error": "bad_request"})


def _export_invoices(user, match, body):
    try:
        ids = json.loads(body)["ids"]
    except (ValueError, KeyError, TypeError):
        return _bad_request()
    if not isinstance(ids, list) or not all(type(item) is int for item in ids):
        return _bad_request()
    invoices = []
    for invoice_id in ids:
        invoice = store.get_invoice(DB, invoice_id)
        if invoice is None or not can_view(user, invoice):
            return _not_found()
        invoices.append(invoice)
    for invoice in invoices:
        store.record_access(DB, user, invoice["id"])
    buffer = io.StringIO()
    fields = ["id", "customer", "total", "status"] + (["internal_notes"] if user.role in FINANCE_ROLES else [])
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(invoice_view(user, invoice) for invoice in invoices)
    return Response(200, buffer.getvalue().encode(), {"Content-Type": "text/csv"})


ROUTES = [
    ("GET", re.compile(r"^/invoices$"), _list_invoices),
    ("GET", re.compile(r"^/invoices/(\d+)$"), _get_invoice),
    ("POST", re.compile(r"^/invoices/export$"), _export_invoices),
]


def handle(method, path, headers=None, body=b""):
    user = store.user_for_key(DB, (headers or {}).get("X-Api-Key"))
    if user is None:
        return _json(401, {"error": "unauthorized"})
    for route_method, pattern, handler in ROUTES:
        match = pattern.match(path)
        if match and route_method == method:
            return handler(user, match, body)
    return _not_found()
