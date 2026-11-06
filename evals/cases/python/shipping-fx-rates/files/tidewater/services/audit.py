"""The audit trail. Written to on every document, shipped to the data warehouse overnight."""

from dataclasses import dataclass
from datetime import date

from tidewater.services.scope import current_document_date


@dataclass(frozen=True)
class AuditEntry:
    kind: str
    reference: str
    business_date: date


TRAIL: list[AuditEntry] = []


def record(kind: str, reference: str) -> None:
    TRAIL.append(AuditEntry(kind, reference, current_document_date()))
