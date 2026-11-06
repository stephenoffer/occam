"""Carrier settlements."""

from __future__ import annotations

from tidewater.domain.settlement.payables import Payable, net_payable
from tidewater.services.audit import record
from tidewater.services.documents import Document, date_field, decimal_field, rows_field, text_field
from tidewater.services.scope import document_scope


def settle(document: Document) -> dict[str, object]:
    currency = text_field(document, "currency")
    payables = [Payable(text_field(row, "reference"), decimal_field(row, "amount"), text_field(row, "currency"))
                for row in rows_field(document, "payables")]
    settled_on = date_field(document, "settled_on")
    with document_scope(settled_on):
        total = net_payable(payables, currency, settled_on)
        record("settlement", text_field(document, "carrier"))
    return {"kind": "settlement", "currency": currency, "total": str(total)}
