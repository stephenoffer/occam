"""Claim assessments."""

from __future__ import annotations

from tidewater.domain.claims.assess import Claim, ClaimAssessor
from tidewater.services.audit import record
from tidewater.services.documents import Document, date_field, decimal_field, text_field
from tidewater.services.scope import document_scope


def assess_claim(document: Document) -> dict[str, object]:
    claim = Claim(text_field(document, "claim_id"), decimal_field(document, "amount"), text_field(document, "currency"),
                  decimal_field(document, "deductible_percent"))
    currency = text_field(document, "settlement_currency")
    with document_scope(date_field(document, "assessed_on")):
        payout = ClaimAssessor(currency).payout(claim)
        record("claim", claim.claim_id)
    return {"kind": "claim", "currency": currency, "total": str(payout)}
