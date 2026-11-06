"""Settlement engine for the co-op's grain elevators.

Scale tickets come in from the elevators. This module grades them, prices them against the board,
posts them to member ledgers, writes member statements, and runs the nightly close.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import pickle
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .taskapp import app

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Season and settings
# ---------------------------------------------------------------------------

ACTIVE_SEASON = "2026-fall"
DEFAULT_FEED_URL = "https://feeds.grainbank.invalid/board.json"
DEFAULT_ALERT_URL = "https://hooks.grainbank.invalid/settlement-alerts"
MAX_FEED_RETRIES = 3
FEED_BACKOFF_SECONDS = 2.0
FEED_TIMEOUT_SECONDS = 10
STALE_TICKET_DAYS = 10
SEASON_RE = re.compile(r"^\d{4}-(spring|fall)$")


def set_season(season: str) -> None:
    """Roll the co-op over to a new season. Statements and checkpoints written after this carry it."""
    global ACTIVE_SEASON
    if not SEASON_RE.match(season):
        raise ValueError(f"not a season: {season!r}")
    ACTIVE_SEASON = season


def season_label() -> str:
    year, half = ACTIVE_SEASON.split("-")
    return f"{half.capitalize()} {year}"


def feed_url() -> str:
    return os.environ.get("GRAINBANK_FEED_URL", DEFAULT_FEED_URL)


def alert_url() -> str:
    return os.environ.get("GRAINBANK_ALERT_URL", DEFAULT_ALERT_URL)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ticket_age_days(ticket: "Ticket") -> int:
    return (utcnow().date() - ticket.weighed_on).days


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GrainbankError(Exception):
    """Base class for everything this package raises on purpose."""


class GradingError(GrainbankError):
    """A ticket that cannot be graded, such as an unknown commodity or impossible weights."""


class FeedError(GrainbankError):
    """The board price feed is down, or does not have the price we need."""


class LedgerError(GrainbankError):
    """A posting the ledger refuses."""


class CheckpointError(GrainbankError):
    """A checkpoint file that cannot be used."""


# ---------------------------------------------------------------------------
# Commodities and tickets
# ---------------------------------------------------------------------------

BUSHEL_PLACES = Decimal("0.01")
PRICE_PLACES = Decimal("0.0001")
CENT_PLACES = Decimal("0.01")


class Grade(enum.Enum):
    NO1 = "No. 1"
    NO2 = "No. 2"
    NO3 = "No. 3"
    SAMPLE = "Sample"


@dataclass(frozen=True)
class CommoditySpec:
    code: str
    pounds_per_bushel: int
    base_moisture: Decimal
    shrink_per_point: Decimal
    no1_test_weight: Decimal
    no2_test_weight: Decimal
    no3_test_weight: Decimal
    max_foreign_material: Decimal


COMMODITIES = {
    "corn": CommoditySpec("corn", 56, Decimal("15.0"), Decimal("1.4"), Decimal("56"), Decimal("54"), Decimal("52"), Decimal("3.0")),
    "soybeans": CommoditySpec("soybeans", 60, Decimal("13.0"), Decimal("1.2"), Decimal("56"), Decimal("54"), Decimal("52"), Decimal("2.0")),
    "wheat": CommoditySpec("wheat", 60, Decimal("13.5"), Decimal("1.3"), Decimal("60"), Decimal("58"), Decimal("56"), Decimal("3.0")),
}


@dataclass
class Ticket:
    """One load across the scale."""

    id: str
    member: str
    commodity: str
    gross_lb: int
    tare_lb: int
    moisture: Decimal
    test_weight: Decimal
    foreign_material: Decimal
    weighed_on: date
    location: str = "north"


def _quantize_bushels(value: Decimal) -> Decimal:
    return value.quantize(BUSHEL_PLACES, rounding=ROUND_HALF_UP)


def _quantize_price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)


def _quantize_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT_PLACES, rounding=ROUND_HALF_UP)


def commodity_spec(code: str) -> CommoditySpec:
    try:
        return COMMODITIES[code]
    except KeyError:
        raise GradingError(f"unknown commodity {code!r}") from None


def ticket_from_dict(data: dict) -> Ticket:
    """Read a ticket as the elevators send it, with decimals and dates as strings."""
    return Ticket(
        id=data["id"],
        member=data["member"],
        commodity=data["commodity"],
        gross_lb=int(data["gross_lb"]),
        tare_lb=int(data["tare_lb"]),
        moisture=Decimal(str(data["moisture"])),
        test_weight=Decimal(str(data["test_weight"])),
        foreign_material=Decimal(str(data.get("foreign_material", "0"))),
        weighed_on=date.fromisoformat(data["weighed_on"]),
        location=data.get("location", "north"),
    )


def ticket_to_dict(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "member": ticket.member,
        "commodity": ticket.commodity,
        "gross_lb": ticket.gross_lb,
        "tare_lb": ticket.tare_lb,
        "moisture": str(ticket.moisture),
        "test_weight": str(ticket.test_weight),
        "foreign_material": str(ticket.foreign_material),
        "weighed_on": ticket.weighed_on.isoformat(),
        "location": ticket.location,
    }


def validate_ticket(ticket: Ticket) -> None:
    commodity_spec(ticket.commodity)
    if ticket.gross_lb <= ticket.tare_lb:
        raise GradingError(f"{ticket.id}: gross {ticket.gross_lb} is not more than tare {ticket.tare_lb}")
    if not Decimal("0") <= ticket.moisture <= Decimal("40"):
        raise GradingError(f"{ticket.id}: moisture {ticket.moisture} is not believable")
    if ticket.test_weight <= 0:
        raise GradingError(f"{ticket.id}: no test weight")
    if ticket.foreign_material < 0:
        raise GradingError(f"{ticket.id}: negative foreign material")


def net_pounds(ticket: Ticket) -> int:
    return ticket.gross_lb - ticket.tare_lb


def moisture_shrink_percent(ticket: Ticket) -> Decimal:
    """Points of water over the commodity's base, each costing a fixed share of the load."""
    spec = commodity_spec(ticket.commodity)
    over = ticket.moisture - spec.base_moisture
    if over <= 0:
        return Decimal("0")
    return over * spec.shrink_per_point


def foreign_material_dock_percent(ticket: Ticket) -> Decimal:
    """Foreign material is docked point for point, above the first half point."""
    over = ticket.foreign_material - Decimal("0.5")
    return over if over > 0 else Decimal("0")


def net_bushels(ticket: Ticket) -> Decimal:
    """Payable bushels after shrink and dock."""
    spec = commodity_spec(ticket.commodity)
    gross = _quantize_bushels(Decimal(net_pounds(ticket)) / spec.pounds_per_bushel)
    # TODO: this rounds the shrink and the dock and then the result. Should round once, at the end.
    shrink = _quantize_bushels(gross * moisture_shrink_percent(ticket) / 100)
    dock = _quantize_bushels(gross * foreign_material_dock_percent(ticket) / 100)
    return _quantize_bushels(gross - shrink - dock)


def grade_ticket(ticket: Ticket) -> Grade:
    spec = commodity_spec(ticket.commodity)
    if ticket.foreign_material > spec.max_foreign_material:
        return Grade.SAMPLE
    if ticket.test_weight >= spec.no1_test_weight:
        return Grade.NO1
    if ticket.test_weight >= spec.no2_test_weight:
        return Grade.NO2
    if ticket.test_weight >= spec.no3_test_weight:
        return Grade.NO3
    return Grade.SAMPLE


# ---------------------------------------------------------------------------
# Board feed
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

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
    for threshold, rate in Ledger.PATRONAGE_TIERS:
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


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


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

    # Bushels already delivered this year, largest first, and the bonus rate above each.
    PATRONAGE_TIERS = (
        (Decimal("50000"), Decimal("0.06")),
        (Decimal("10000"), Decimal("0.03")),
    )

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


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


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
    return f"{ACTIVE_SEASON}-{member}.txt"


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


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
        self.season = season or ACTIVE_SEASON
        self.saved_at: datetime | None = None

    def __setstate__(self, state: dict) -> None:
        """Version 2 checkpoints kept a plain position and no season."""
        if state.get("version", 1) < 3:
            state = dict(state)
            state["cursor"] = _Cursor(state.pop("position", 0))
            state.setdefault("season", ACTIVE_SEASON)
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


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


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


def _read_tickets(path) -> list[Ticket]:
    return [ticket_from_dict(item) for item in json.loads(Path(path).read_text())]


@app.task
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
        app.send_task(f"{__name__}.send_statement", member, ledger_path, statements_dir)
    return {
        "season": ACTIVE_SEASON,
        "settled": [priced.ticket_id for priced in settled],
        "failed": sorted(failures),
        "members": members,
        "bushels": str(sum((priced.bushels for priced in settled), Decimal("0"))),
        "amount": str(sum((priced.amount for priced in settled), Decimal("0.00"))),
    }


@app.task
def send_statement(member: str, ledger_path: str, statements_dir: str) -> str:
    ledger = Ledger.load(ledger_path)
    target = Path(statements_dir) / statement_filename(member)
    target.write_text(render_statement(member, ledger))
    return target.name


@app.task
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


@app.task
def reverse_ticket(ticket_id: str, reason: str, ledger_path: str) -> dict:
    ledger = Ledger.load(ledger_path)
    entry = ledger.reverse(ticket_id, reason)
    ledger.save(ledger_path)
    return {"member": entry.member, "amount": str(entry.amount)}
