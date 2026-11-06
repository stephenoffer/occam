"""Member statements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import settings
from .clock import utcnow
from .ledger import Ledger
from .settings import season_label


@dataclass
class StatementLine:
    ticket_id: str
    bushels: Decimal
    amount: Decimal
    memo: str


@dataclass
class Statement:
    member: str
    season: str
    generated_on: date
    lines: list[StatementLine] = field(default_factory=list)

    @property
    def total_bushels(self) -> Decimal:
        return sum((line.bushels for line in self.lines), Decimal("0"))

    @property
    def balance(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0.00"))


def build_statement(member: str, ledger: Ledger) -> Statement:
    lines = [
        StatementLine(entry.ticket_id or "-", entry.bushels, entry.amount, entry.memo)
        for entry in ledger.entries_for(member)
    ]
    return Statement(member, season_label(), utcnow().date(), lines)


def render_statement(member: str, ledger: Ledger) -> str:
    statement = build_statement(member, ledger)
    out = [
        "Grainbank Co-op member statement",
        f"Member: {statement.member}",
        f"Season: {statement.season}",
        f"Generated: {statement.generated_on.isoformat()}",
        "",
        f"{'Ticket':<12}{'Bushels':>12}{'Amount':>12}  Memo",
    ]
    for line in statement.lines:
        out.append(f"{line.ticket_id:<12}{line.bushels:>12}{line.amount:>12}  {line.memo}")
    out.append("")
    out.append(f"Total bushels: {statement.total_bushels}")
    out.append(f"Balance: {statement.balance}")
    return "\n".join(out) + "\n"


def statement_filename(member: str) -> str:
    return f"{settings.ACTIVE_SEASON}-{member}.txt"
