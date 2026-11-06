"""Every posting to every member's account."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .clock import utcnow
from .errors import LedgerError
from .grading import Ticket, _quantize_cents
from .pricing import PATRONAGE_TIERS, PricedTicket, price_ticket


@dataclass
class LedgerEntry:
    member: str
    amount: Decimal
    bushels: Decimal
    memo: str
    posted_at: datetime
    ticket_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "member": self.member,
            "amount": str(self.amount),
            "bushels": str(self.bushels),
            "memo": self.memo,
            "posted_at": self.posted_at.isoformat(),
            "ticket_id": self.ticket_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LedgerEntry":
        return cls(
            member=data["member"],
            amount=Decimal(data["amount"]),
            bushels=Decimal(data["bushels"]),
            memo=data["memo"],
            posted_at=datetime.fromisoformat(data["posted_at"]),
            ticket_id=data.get("ticket_id"),
        )


class Ledger:
    """Every posting to every member's account, oldest first."""

    PATRONAGE_TIERS = PATRONAGE_TIERS

    def __init__(self, entries: list[LedgerEntry] | None = None):
        self.entries: list[LedgerEntry] = list(entries or [])

    def post(self, member: str, amount: Decimal, bushels: Decimal = Decimal("0"), memo: str = "", ticket_id: str | None = None) -> LedgerEntry:
        entry = LedgerEntry(member, _quantize_cents(amount), bushels, memo, utcnow(), ticket_id)
        self.entries.append(entry)
        return entry

    def has_ticket(self, ticket_id: str) -> bool:
        return any(entry.ticket_id == ticket_id for entry in self.entries)

    def post_settlement(self, ticket: Ticket, board: Decimal | None = None) -> PricedTicket:
        """Price a ticket and post it. A ticket can only be settled once."""
        if self.has_ticket(ticket.id):
            raise LedgerError(f"{ticket.id} has already been settled")
        priced = price_ticket(ticket, self, board)
        self.post(ticket.member, priced.amount, priced.bushels, f"{priced.commodity} {priced.grade.value}", ticket.id)
        return priced

    def reverse(self, ticket_id: str, reason: str) -> LedgerEntry:
        """Post the opposite of a settled ticket, keeping the original on the record."""
        originals = [entry for entry in self.entries if entry.ticket_id == ticket_id]
        if not originals:
            raise LedgerError(f"{ticket_id} has not been settled")
        if len(originals) > 1:
            raise LedgerError(f"{ticket_id} has already been reversed")
        original = originals[0]
        return self.post(original.member, -original.amount, -original.bushels, f"reversal: {reason}", ticket_id)

    def balance(self, member: str) -> Decimal:
        return sum((entry.amount for entry in self.entries if entry.member == member), Decimal("0.00"))

    def ytd_bushels(self, member: str) -> Decimal:
        return sum((entry.bushels for entry in self.entries if entry.member == member), Decimal("0"))

    def members(self) -> list[str]:
        return sorted({entry.member for entry in self.entries})

    def entries_for(self, member: str) -> list[LedgerEntry]:
        return [entry for entry in self.entries if entry.member == member]

    def to_json(self) -> str:
        return json.dumps([entry.to_dict() for entry in self.entries], indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Ledger":
        return cls([LedgerEntry.from_dict(item) for item in json.loads(text)])

    def save(self, path) -> None:
        target = Path(path)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(self.to_json())
        temporary.replace(target)

    @classmethod
    def load(cls, path) -> "Ledger":
        target = Path(path)
        if not target.exists():
            return cls()
        return cls.from_json(target.read_text())
