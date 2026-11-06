from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
import enum
import os
import re




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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ticket_age_days(ticket: "Ticket") -> int:
    return (utcnow().date() - ticket.weighed_on).days


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
