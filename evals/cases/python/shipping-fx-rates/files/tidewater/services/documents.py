"""Pulling typed fields out of raw JSON documents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from tidewater.core.errors import DocumentError

Document = Mapping[str, object]


def text_field(document: Document, name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value:
        raise DocumentError(f"{name} is required")
    return value


def date_field(document: Document, name: str) -> date:
    try:
        return date.fromisoformat(text_field(document, name))
    except ValueError as exc:
        raise DocumentError(f"{name} isn't a date") from exc


def decimal_field(document: Document, name: str) -> Decimal:
    try:
        return Decimal(text_field(document, name))
    except InvalidOperation as exc:
        raise DocumentError(f"{name} isn't a number") from exc


def rows_field(document: Document, name: str) -> list[Document]:
    value = document.get(name)
    if not isinstance(value, list):
        raise DocumentError(f"{name} must be a list")
    return [row for row in value if isinstance(row, dict)]
