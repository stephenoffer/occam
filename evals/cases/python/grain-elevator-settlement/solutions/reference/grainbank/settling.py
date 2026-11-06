"""Settling tickets: the step both the nightly close and a resumed checkpoint are made of."""

from __future__ import annotations

import logging
from decimal import Decimal

from .alerts import send_alert
from .clock import ticket_age_days
from .errors import GrainbankError
from .grading import Ticket
from .ledger import Ledger
from .pricing import PricedTicket
from .settings import STALE_TICKET_DAYS

log = logging.getLogger("grainbank.settlement")


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
