from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.request import urlopen
import json
import logging
import time

from .fundamentals import FEED_BACKOFF_SECONDS, FEED_TIMEOUT_SECONDS, MAX_FEED_RETRIES, feed_url
from .fundamentals import FEED_TIMEOUT_SECONDS, alert_url
from .fundamentals import FeedError
from .fundamentals import Grade, Ticket, _quantize_cents, _quantize_price, commodity_spec, grade_ticket, net_bushels, validate_ticket
from .fundamentals import GradingError
from .fundamentals import LedgerError
from .fundamentals import Ticket, _quantize_cents
from .fundamentals import utcnow

log = logging.getLogger("grainbank.settlement")




def send_alert(subject: str, details: str = "") -> bool:
    """Tell the on-call channel. An alert that cannot be sent is logged, and never stops the work."""
    body = json.dumps({"subject": subject, "details": details, "sent_at": utcnow().isoformat()}).encode()
    request = Request(alert_url(), data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=FEED_TIMEOUT_SECONDS):
            return True
    except (URLError, ValueError) as exc:
        log.error("could not send alert %r: %s", subject, exc)
        return False



_PRICE_CACHE: dict[str, Decimal] = {}


def fetch_board() -> dict[str, Decimal]:
    """Fetch today's board prices, retrying, and raise an alert if the feed stays down."""
    last_error = None
    for attempt in range(MAX_FEED_RETRIES):
        try:
            with urlopen(feed_url(), timeout=FEED_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode())
            return {code: Decimal(str(price)) for code, price in payload["prices"].items()}
        except (URLError, ValueError, KeyError) as exc:
            last_error = exc
            log.warning("board feed attempt %d failed: %s", attempt + 1, exc)
            if attempt + 1 < MAX_FEED_RETRIES:
                time.sleep(FEED_BACKOFF_SECONDS * (attempt + 1))
    send_alert("board feed down", str(last_error))
    raise FeedError(f"board feed down after {MAX_FEED_RETRIES} attempts: {last_error}")


def board_price(commodity: str) -> Decimal:
    if commodity not in _PRICE_CACHE:
        _PRICE_CACHE.update(fetch_board())
    try:
        return _PRICE_CACHE[commodity]
    except KeyError:
        raise FeedError(f"the board has no price for {commodity}") from None


def clear_price_cache() -> None:
    _PRICE_CACHE.clear()


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
