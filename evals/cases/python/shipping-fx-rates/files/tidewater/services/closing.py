"""Period-end revaluation."""

from __future__ import annotations

from tidewater.domain.ledger.revaluation import Balance, revalue
from tidewater.services.audit import record
from tidewater.services.documents import Document, date_field, decimal_field, rows_field, text_field
from tidewater.services.scope import document_scope


def close_period(document: Document) -> dict[str, object]:
    currency = text_field(document, "reporting_currency")
    balances = [Balance(decimal_field(row, "amount"), text_field(row, "currency")) for row in rows_field(document, "balances")]
    period_end = date_field(document, "period_end")
    with document_scope(period_end):
        total = revalue(balances, currency)
        record("closing", period_end.isoformat())
    return {"kind": "closing", "currency": currency, "total": str(total)}
