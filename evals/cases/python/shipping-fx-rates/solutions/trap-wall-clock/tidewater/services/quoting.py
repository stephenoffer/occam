"""Freight quotes."""

from __future__ import annotations

from decimal import Decimal

from tidewater.core.clock import today
from tidewater.domain.adjustments.registry import apply_adjustments
from tidewater.domain.rating.pricing import price_freight
from tidewater.services.audit import record
from tidewater.services.documents import Document, date_field, decimal_field, text_field
from tidewater.services.scope import document_scope


def quote(document: Document) -> dict[str, object]:
    lane = text_field(document, "lane")
    currency = text_field(document, "currency")
    booked_on = date_field(document, "booked_on")
    with document_scope(booked_on):
        price = price_freight(lane, decimal_field(document, "tonnes"), currency, today())
        adjustments = apply_adjustments(lane, currency, price.subtotal, today())
        record("quote", lane)
    total = price.subtotal + sum((line.amount for line in adjustments), Decimal(0))
    return {
        "kind": "quote",
        "currency": currency,
        "freight": str(price.freight),
        "fuel": str(price.fuel),
        "adjustments": {line.code: str(line.amount) for line in adjustments},
        "total": str(total),
    }
