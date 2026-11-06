"""Invoice and export endpoints."""

from __future__ import annotations

import contextlib
import csv
import os
import sqlite3
import subprocess

from .. import store
from ..auth import authenticated
from ..http import BadRequest, NotFound, Request, Response, RouteTable, json_response
from ..models import INVOICE_STATUSES, Invoice
from ..services import billing
from ..utils import dates
from ..utils.formatting import display_amount

routes = RouteTable()

EXPORT_COLUMNS = ("number", "status", "currency", "subtotal_cents", "tax_cents", "total_cents", "issued_at", "due_on")


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
        "refunded_cents": invoice.refunded_cents,
        "total_display": display_amount(invoice.total_cents, invoice.currency),
        "issued_at": invoice.issued_at,
        "due_on": invoice.due_on,
    }


def _require_invoice(request: Request) -> Invoice:
    invoice = store.get_invoice(request.conn, request.tenant_id, request.param_int("invoice_id"))
    if invoice is None:
        raise NotFound("invoice not found")
    return invoice


@routes.get("/invoices")
@authenticated
def list_invoices(request: Request) -> Response:
    page = request.query_int("page", 0)
    limit = request.query_int("limit", 25)
    status = request.query.get("status")
    if status and status not in INVOICE_STATUSES:
        raise BadRequest("unknown status")
    invoices = store.list_invoices(request.conn, request.tenant_id, limit, page * limit, status=status)
    results = []
    for invoice in invoices:
        customer = store.get_customer(request.conn, request.tenant_id, invoice.customer_id)
        lines = store.lines_for_invoice(request.conn, invoice.id)
        item = _invoice_json(invoice)
        item["customer_name"] = customer.name
        item["line_count"] = len(lines)
        results.append(item)
    return json_response({"invoices": results})


@routes.get("/invoices/lookup")
@authenticated
def lookup_invoices(request: Request) -> Response:
    raw = request.query.get("ids", "")
    try:
        ids = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise BadRequest("ids must be a comma separated list of integers") from exc
    invoices = store.invoices_by_ids(request.conn, request.tenant_id, ids)
    return json_response({"invoices": [_invoice_json(i) for i in invoices]})


@routes.get("/invoices/{invoice_id}")
@authenticated
def get_invoice(request: Request) -> Response:
    invoice = _require_invoice(request)
    payload = _invoice_json(invoice)
    payload["lines"] = [
        {"description": l.description, "quantity": l.quantity, "unit_cents": l.unit_cents, "amount_cents": l.amount_cents}
        for l in store.lines_for_invoice(request.conn, invoice.id)
    ]
    return json_response(payload)


@routes.get("/invoices/{invoice_id}/pdf")
@authenticated
def invoice_pdf(request: Request) -> Response:
    from invoice_render import render_invoice_pdf

    invoice = _require_invoice(request)
    lines = store.lines_for_invoice(request.conn, invoice.id)
    return Response(200, render_invoice_pdf(invoice, lines), {"Content-Type": "application/pdf"})


@routes.post("/invoices/{invoice_id}/void")
@authenticated
def void_invoice(request: Request) -> Response:
    invoice = billing.void_invoice(request.conn, request.tenant_id, request.param_int("invoice_id"))
    return json_response(_invoice_json(invoice))


@routes.post("/invoices/{invoice_id}/refund")
@authenticated
def refund_invoice(request: Request) -> Response:
    invoice = _require_invoice(request)
    body = request.json()
    if "amount_cents" not in body:
        raise BadRequest("amount_cents is required")
    refunded = billing.refund_invoice(
        request.conn, request.app.gateway, tenant_id=request.tenant_id, invoice_id=invoice.id,
        amount_cents=int(body["amount_cents"]),
    )
    return json_response(_invoice_json(refunded))


def _write_export(conn: sqlite3.Connection, tenant_id: int, name: str, export_dir: str) -> str:
    os.makedirs(export_dir, exist_ok=True)
    csv_path = os.path.join(export_dir, f"{name}.csv")
    with contextlib.suppress(FileNotFoundError):
        os.remove(f"{csv_path}.gz")
    invoices = store.list_invoices(conn, tenant_id, limit=100_000, offset=0)
    with open(csv_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(EXPORT_COLUMNS)
        for invoice in invoices:
            writer.writerow([getattr(invoice, column) for column in EXPORT_COLUMNS])
    subprocess.run(f"gzip -f {csv_path}", shell=True, check=True)
    return f"{csv_path}.gz"


@routes.post("/exports")
@authenticated
def create_export(request: Request) -> Response:
    name = request.json().get("name") or f"invoices-{dates.utc_today().isoformat()}"
    path = _write_export(request.conn, request.tenant_id, name, request.app.settings.export_dir)
    return json_response({"file": os.path.basename(path)}, status=201)


@routes.get("/exports/download")
@authenticated
def download_export(request: Request) -> Response:
    filename = request.query.get("file")
    if not filename:
        raise BadRequest("file is required")
    path = os.path.join(request.app.settings.export_dir, filename)
    if not os.path.isfile(path):
        raise NotFound("export not found")
    with open(path, "rb") as handle:
        return Response(status=200, body=handle.read(), headers={"Content-Type": "application/gzip"})
