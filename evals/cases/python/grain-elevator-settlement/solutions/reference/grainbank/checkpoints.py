"""A nightly close part way through, pickled so that a restarted worker can finish it."""

from __future__ import annotations

import pickle
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import settings
from .clock import utcnow
from .errors import CheckpointError
from .grading import Ticket
from .ledger import Ledger
from .pricing import PricedTicket
from .settling import settle_ticket


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
