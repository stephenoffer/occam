from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import json
import logging
import pickle

from . import fundamentals as settings
from .accounts import Ledger
from .accounts import PricedTicket
from .accounts import _PRICE_CACHE, clear_price_cache, fetch_board
from .accounts import send_alert
from .fundamentals import CheckpointError
from .fundamentals import GrainbankError
from .fundamentals import STALE_TICKET_DAYS
from .fundamentals import Ticket
from .fundamentals import Ticket, ticket_from_dict
from .fundamentals import season_label
from .fundamentals import ticket_age_days
from .fundamentals import utcnow
from .taskapp import app

log = logging.getLogger("grainbank.settlement")


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




def settle_ticket(ticket: Ticket, ledger: Ledger, board: Decimal | None = None) -> PricedTicket:
    """Settle one ticket, flagging it to on-call if it took too long to reach us."""
    if ticket_age_days(ticket) > STALE_TICKET_DAYS:
        send_alert("stale ticket", f"{ticket.id} was weighed on {ticket.weighed_on.isoformat()}")
    return ledger.post_settlement(ticket, board)


def settle_batch(tickets: list[Ticket], ledger: Ledger, board: Decimal | None = None) -> tuple[list[PricedTicket], dict[str, str]]:
    """Settle what can be settled. One bad ticket should not hold up everybody else's."""
    settled, failures = [], {}
    for ticket in tickets:
        try:
            settled.append(settle_ticket(ticket, ledger, board))
        except GrainbankError as exc:
            log.warning("could not settle %s: %s", ticket.id, exc)
            failures[ticket.id] = str(exc)
    return settled, failures


class _Cursor:
    """How far through its tickets a nightly close has got."""

    def __init__(self, index: int = 0, last_ticket: str | None = None):
        self.index = index
        self.last_ticket = last_ticket

    def advance(self, ticket_id: str) -> None:
        self.index += 1
        self.last_ticket = ticket_id


class SettlementCheckpoint:
    """A nightly close part way through, pickled so that a restarted worker can finish it."""

    VERSION = 3

    def __init__(self, tickets: list[Ticket], season: str | None = None):
        self.version = self.VERSION
        self.tickets = list(tickets)
        self.cursor = _Cursor()
        self.results: list[PricedTicket] = []
        self.season = season or settings.ACTIVE_SEASON
        self.saved_at: datetime | None = None

    def __setstate__(self, state: dict) -> None:
        """Version 2 checkpoints kept a plain position and no season."""
        if state.get("version", 1) < 3:
            state = dict(state)
            state["cursor"] = _Cursor(state.pop("position", 0))
            state.setdefault("season", settings.ACTIVE_SEASON)
            state["version"] = self.VERSION
        self.__dict__.update(state)

    def remaining(self) -> list[Ticket]:
        return self.tickets[self.cursor.index:]

    def resume(self, ledger: Ledger, board: Decimal | None = None) -> list[PricedTicket]:
        """Settle whatever is left, skipping nothing and settling nothing twice."""
        settled = []
        for ticket in self.remaining():
            priced = settle_ticket(ticket, ledger, board)
            self.results.append(priced)
            self.cursor.advance(ticket.id)
            settled.append(priced)
        return settled


def save_checkpoint(checkpoint: SettlementCheckpoint, path) -> None:
    checkpoint.saved_at = utcnow()
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(checkpoint, handle, protocol=2)
    temporary.replace(target)


def load_checkpoint(path) -> SettlementCheckpoint:
    try:
        with Path(path).open("rb") as handle:
            checkpoint = pickle.load(handle)
    except OSError as exc:
        raise CheckpointError(f"cannot read checkpoint {path}: {exc.strerror}") from exc
    if not isinstance(checkpoint, SettlementCheckpoint):
        raise CheckpointError(f"{path} does not hold a settlement checkpoint")
    return checkpoint


def _read_tickets(path) -> list[Ticket]:
    return [ticket_from_dict(item) for item in json.loads(Path(path).read_text())]


@app.task(name="grainbank.settlement.nightly_close")
def nightly_close(tickets_path: str, ledger_path: str, statements_dir: str, checkpoint_path: str | None = None) -> dict:
    """Settle the day's tickets, then queue a statement for every member who delivered."""
    tickets = _read_tickets(tickets_path)
    ledger = Ledger.load(ledger_path)
    settled, failures = settle_batch(tickets, ledger)
    ledger.save(ledger_path)
    if failures:
        send_alert("nightly close had failures", json.dumps(failures, sort_keys=True))
    if checkpoint_path:
        checkpoint = SettlementCheckpoint(tickets)
        for priced in settled:
            checkpoint.results.append(priced)
            checkpoint.cursor.advance(priced.ticket_id)
        save_checkpoint(checkpoint, checkpoint_path)
    members = sorted({priced.member for priced in settled})
    for member in members:
        app.send_task("grainbank.settlement.send_statement", member, ledger_path, statements_dir)
    return {
        "season": settings.ACTIVE_SEASON,
        "settled": [priced.ticket_id for priced in settled],
        "failed": sorted(failures),
        "members": members,
        "bushels": str(sum((priced.bushels for priced in settled), Decimal("0"))),
        "amount": str(sum((priced.amount for priced in settled), Decimal("0.00"))),
    }


@app.task(name="grainbank.settlement.send_statement")
def send_statement(member: str, ledger_path: str, statements_dir: str) -> str:
    ledger = Ledger.load(ledger_path)
    target = Path(statements_dir) / statement_filename(member)
    target.write_text(render_statement(member, ledger))
    return target.name


@app.task(name="grainbank.settlement.refresh_board_prices")
def refresh_board_prices() -> dict:
    clear_price_cache()
    _PRICE_CACHE.update(fetch_board())
    return {code: str(price) for code, price in sorted(_PRICE_CACHE.items())}


@app.task(name="settlement.reconcile")
def reconcile_member(member: str, ledger_path: str, expected_balance: str) -> dict:
    """Compare a member's balance with what accounting expects, and alert on a mismatch."""
    balance = Ledger.load(ledger_path).balance(member)
    expected = Decimal(expected_balance)
    if balance != expected:
        send_alert("ledger mismatch", f"{member}: ledger has {balance}, accounting has {expected}")
    return {"member": member, "balance": str(balance), "matches": balance == expected}


@app.task(name="grainbank.settlement.reverse_ticket")
def reverse_ticket(ticket_id: str, reason: str, ledger_path: str) -> dict:
    ledger = Ledger.load(ledger_path)
    entry = ledger.reverse(ticket_id, reason)
    ledger.save(ledger_path)
    return {"member": entry.member, "amount": str(entry.amount)}
