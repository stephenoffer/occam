"""The tasks the workers run. Their registered names are what the scheduler and the broker know them by, so they stay as they are."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from . import settings
from .alerts import send_alert
from .board import _PRICE_CACHE, clear_price_cache, fetch_board
from .checkpoints import SettlementCheckpoint, save_checkpoint
from .grading import Ticket, ticket_from_dict
from .ledger import Ledger
from .settling import settle_batch
from .statements import render_statement, statement_filename
from .taskapp import app


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
