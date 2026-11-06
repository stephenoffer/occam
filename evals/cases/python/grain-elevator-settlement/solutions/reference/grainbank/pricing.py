"""What a ticket pays. Takes the ledger only as something that knows what a member has delivered."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .board import board_price
from .errors import GradingError
from .grading import Grade, Ticket, _quantize_cents, _quantize_price, commodity_spec, grade_ticket, net_bushels, validate_ticket

BASIS_BY_LOCATION = {
    "north": Decimal("-0.18"),
    "river": Decimal("-0.05"),
    "east": Decimal("-0.12"),
}
GRADE_DISCOUNTS = {
    Grade.NO1: Decimal("0.00"),
    Grade.NO2: Decimal("0.03"),
    Grade.NO3: Decimal("0.08"),
    Grade.SAMPLE: Decimal("0.35"),
}
DRYING_RATE_PER_POINT = Decimal("0.025")
# Bushels already delivered this year, largest first, and the bonus rate above each.
PATRONAGE_TIERS = (
    (Decimal("50000"), Decimal("0.06")),
    (Decimal("10000"), Decimal("0.03")),
)


@dataclass
class PricedTicket:
    ticket_id: str
    member: str
    commodity: str
    grade: Grade
    bushels: Decimal
    board: Decimal
    basis: Decimal
    grade_discount: Decimal
    drying: Decimal
    patronage: Decimal
    price_per_bushel: Decimal
    amount: Decimal

    def to_dict(self) -> dict:
        return {
            "ticket": self.ticket_id,
            "member": self.member,
            "commodity": self.commodity,
            "grade": self.grade.value,
            "bushels": str(self.bushels),
            "board": str(self.board),
            "basis": str(self.basis),
            "grade_discount": str(self.grade_discount),
            "drying": str(self.drying),
            "patronage": str(self.patronage),
            "price_per_bushel": str(self.price_per_bushel),
            "amount": str(self.amount),
        }


def basis_for(location: str) -> Decimal:
    try:
        return BASIS_BY_LOCATION[location]
    except KeyError:
        raise GradingError(f"unknown location {location!r}") from None


def drying_charge(ticket: Ticket) -> Decimal:
    """What it costs per bushel to bring a wet load down to the commodity's base moisture."""
    spec = commodity_spec(ticket.commodity)
    over = ticket.moisture - spec.base_moisture
    if over <= 0:
        return Decimal("0")
    return _quantize_price(over * DRYING_RATE_PER_POINT)


def patronage_rate(ytd_bushels: Decimal) -> Decimal:
    """The patronage bonus a member earns, from how much they have already delivered this year."""
    for threshold, rate in PATRONAGE_TIERS:
        if ytd_bushels > threshold:
            return rate
    return Decimal("0")


def price_ticket(ticket: Ticket, ledger: "Ledger", board: Decimal | None = None) -> PricedTicket:
    """Work out what a ticket pays, given what the member has delivered so far."""
    validate_ticket(ticket)
    quote = board if board is not None else board_price(ticket.commodity)
    grade = grade_ticket(ticket)
    bushels = net_bushels(ticket)
    basis = basis_for(ticket.location)
    discount = GRADE_DISCOUNTS[grade]
    drying = drying_charge(ticket)
    patronage = _quantize_price(quote * patronage_rate(ledger.ytd_bushels(ticket.member)))
    price = _quantize_price(quote + basis - discount - drying + patronage)
    return PricedTicket(
        ticket_id=ticket.id,
        member=ticket.member,
        commodity=ticket.commodity,
        grade=grade,
        bushels=bushels,
        board=quote,
        basis=basis,
        grade_discount=discount,
        drying=drying,
        patronage=patronage,
        price_per_bushel=price,
        amount=_quantize_cents(price * bushels),
    )
