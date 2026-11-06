"""Berth charge estimates."""

from __future__ import annotations

from tidewater.domain.berthing.charges import spot_rate
from tidewater.services.documents import Document, date_field, decimal_field, text_field


def berth_charge(document: Document) -> dict[str, object]:
    total = spot_rate(text_field(document, "berth_class"), decimal_field(document, "hours"), date_field(document, "booked_on"))
    return {"kind": "berth-charge", "total": str(total)}
