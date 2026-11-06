"""Invoices."""

from __future__ import annotations

from decimal import Decimal

from tidewater.core.clock import today
from tidewater.domain.adjustments.registry import apply_adjustments
from tidewater.domain.billing.totals import InvoiceLine, invoice_subtotal
from tidewater.services.audit import record
from tidewater.services.documents import Document, date_field, decimal_field, rows_field, text_field
from tidewater.services.scope import document_scope


def invoice(document: Document) -> dict[str, object]:
    lane = text_field(document, "lane")
    currency = text_field(document, "currency")
    due_on = date_field(document, "due_on")
    lines = [InvoiceLine(text_field(row, "description"), decimal_field(row, "amount"), text_field(row, "currency"))
             for row in rows_field(document, "lines")]
    issued_on = date_field(document, "issued_on")
    with document_scope(issued_on):
        subtotal = invoice_subtotal(lines, currency, today())
        adjustments = apply_adjustments(lane, currency, subtotal, today())
        record("invoice", text_field(document, "invoice_id"))
    total = subtotal + sum((line.amount for line in adjustments), Decimal(0))
    return {
        "kind": "invoice",
        "currency": currency,
        "due_on": due_on.isoformat(),
        "adjustments": {line.code: str(line.amount) for line in adjustments},
        "total": str(total),
    }
