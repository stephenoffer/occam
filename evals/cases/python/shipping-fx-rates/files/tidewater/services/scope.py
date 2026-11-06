"""Which document is being worked on, for the audit trail."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date

_document_date: ContextVar[date] = ContextVar("document_date")


@contextmanager
def document_scope(business_date: date) -> Iterator[None]:
    token = _document_date.set(business_date)
    try:
        yield
    finally:
        _document_date.reset(token)


def current_document_date() -> date:
    """The business date of the document being worked on."""
    return _document_date.get()
