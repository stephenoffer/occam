"""Pushes contract bushels and prices to the feed mill. Owned by the feed mill's IT team."""

from grainbank import settlement
from grainbank.settlement import COMMODITIES, FeedError, Grade, Ticket, ticket_from_dict


def price_or_none(commodity):
    try:
        return settlement.board_price(commodity)
    except FeedError:
        return None


def contract_bushels(rows):
    """Payable bushels per commodity, leaving out loads that graded below the contract."""
    totals = {code: 0 for code in COMMODITIES}
    for row in rows:
        ticket: Ticket = ticket_from_dict(row)
        if settlement.grade_ticket(ticket) is not Grade.SAMPLE:
            totals[ticket.commodity] += settlement.net_bushels(ticket)
    return totals


def settle_for_mill(rows, ledger, board):
    results, failures = settlement.settle_batch([ticket_from_dict(row) for row in rows], ledger, board)
    return [priced.ticket_id for priced in results], failures
