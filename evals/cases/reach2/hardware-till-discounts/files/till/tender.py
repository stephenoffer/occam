"""Taking payment: how much each tender covers and what change is due.

Card tenders are authorised for an exact amount, so they can never be more than what's left to
pay; only cash gives change.
"""

from __future__ import annotations

from dataclasses import dataclass

TENDER_TYPES = ("cash", "card")


class TenderError(ValueError):
    """Payment that doesn't settle the sale."""


@dataclass(frozen=True)
class Tender:
    type: str
    pence: int


def parse_tenders(entries: list[dict]) -> list[Tender]:
    tenders = []
    for entry in entries:
        kind = str(entry.get("type", "")).lower()
        if kind not in TENDER_TYPES:
            raise TenderError(f"unknown tender type {entry.get('type')!r}")
        pence = entry.get("pence")
        if not isinstance(pence, int) or isinstance(pence, bool) or pence <= 0:
            raise TenderError(f"{kind} tender needs a positive whole number of pence")
        tenders.append(Tender(kind, pence))
    if not tenders:
        raise TenderError("no payment taken")
    return tenders


def settle(total_pence: int, tenders: list[Tender]) -> int:
    """Check the tenders cover the total and return the change due, in pence."""
    remaining = total_pence
    cash = 0
    for tender in tenders:
        if tender.type == "card":
            if tender.pence > max(remaining, 0):
                raise TenderError("a card payment can't be more than the amount left to pay")
            remaining -= tender.pence
        else:
            cash += tender.pence
    if cash < remaining:
        raise TenderError(f"{remaining - cash}p still to pay")
    return cash - remaining
