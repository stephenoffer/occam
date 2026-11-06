"""Customs declarations."""

from __future__ import annotations

from tidewater.domain.customs.declaration import assess_declaration
from tidewater.domain.customs.valuation import DeclaredItem
from tidewater.services.audit import record
from tidewater.services.documents import Document, date_field, decimal_field, rows_field, text_field
from tidewater.services.scope import document_scope


def file_declaration(document: Document) -> dict[str, object]:
    currency = text_field(document, "importing_currency")
    items = [DeclaredItem(text_field(row, "hs_code"), decimal_field(row, "value"), text_field(row, "currency"))
             for row in rows_field(document, "items")]
    with document_scope(date_field(document, "filed_on")):
        assessment = assess_declaration(items, currency)
        record("declaration", text_field(document, "declaration_id"))
    return {"kind": "declaration", "currency": currency, "items": assessment.item_count, "total": str(assessment.total_duty)}
