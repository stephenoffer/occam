"""Reading the tapes stores upload.

A tape is one trading day of one store's sales, named `<store>-<YYYY-MM-DD>.tape`, one JSON
object per line, one line per sale. The format is described in docs/tape-format.md and is the
contract between the stores and head office (ADR 0002): head office reads tapes with this module
and nothing else, and never imports store-side code.

A record that doesn't check out is set aside as quarantined, with the reason, rather than stopping
the whole tape: finance would rather post 199 good sales and chase one than post none.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

KNOWN_VERSIONS = {1, 2}
DISCOUNT_REASONS = {"STAFF", "PROMO", "DAMAGED"}
TENDERS = {"cash", "card"}
TAPE_NAME = re.compile(r"^(?P<store>[A-Z0-9]+)-(?P<day>\d{4}-\d{2}-\d{2})\.tape$")


class TapeRecordError(ValueError):
    pass


@dataclass(frozen=True)
class TapeLine:
    sku: str
    dept: str
    qty: int
    unit: int
    discount: int = 0
    discount_reason: str | None = None

    @property
    def amount(self) -> int:
        """What the line took, net of its discount."""
        return self.qty * self.unit - self.discount


@dataclass(frozen=True)
class TapeSale:
    store: str
    till: int
    sale: str
    at: str
    lines: tuple[TapeLine, ...]
    tenders: dict
    change: int

    @property
    def line_total(self) -> int:
        return sum(line.amount for line in self.lines)

    @property
    def paid(self) -> int:
        return sum(self.tenders.values()) - self.change


@dataclass(frozen=True)
class Quarantined:
    tape: str
    line_no: int
    reason: str


@dataclass
class Tape:
    path: Path
    store: str
    day: date
    sales: list[TapeSale] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)


def _whole(value, what: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise TapeRecordError(f"{what} must be a whole number of at least {minimum}")
    return value


def _discount(value, version: int, gross: int) -> tuple[int, str | None]:
    """A version 2 line may carry {"pence": int, "reason": str}, taken off the line's value."""
    if value is None:
        return 0, None
    if version < 2:
        raise TapeRecordError("line discounts need version 2")
    if not isinstance(value, dict) or value.get("reason") not in DISCOUNT_REASONS:
        raise TapeRecordError(f"discount reason must be one of {', '.join(sorted(DISCOUNT_REASONS))}")
    pence = _whole(value.get("pence"), "discount", 1)
    if pence > gross:
        raise TapeRecordError("discount is more than the line's value")
    return pence, value["reason"]


def check_record(record: object) -> TapeSale:
    if not isinstance(record, dict):
        raise TapeRecordError("not a JSON object")
    if record.get("v") not in KNOWN_VERSIONS:
        raise TapeRecordError(f"unknown version {record.get('v')!r}")
    for key in ("store", "till", "sale", "at", "lines", "tenders", "change"):
        if key not in record:
            raise TapeRecordError(f"missing {key}")
    if not isinstance(record["lines"], list) or not record["lines"]:
        raise TapeRecordError("a sale needs at least one line")
    lines = []
    for item in record["lines"]:
        if not isinstance(item, dict) or not item.get("sku") or not item.get("dept"):
            raise TapeRecordError("a line needs sku and dept")
        qty, unit = _whole(item.get("qty"), "qty", 1), _whole(item.get("unit"), "unit")
        discount, reason = _discount(item.get("discount"), record["v"], qty * unit)
        lines.append(TapeLine(str(item["sku"]), str(item["dept"]), qty, unit, discount, reason))
    tenders: dict[str, int] = {}
    for tender in record["tenders"]:
        kind = tender.get("type") if isinstance(tender, dict) else None
        if kind not in TENDERS:
            raise TapeRecordError(f"unknown tender {kind!r}")
        tenders[kind] = tenders.get(kind, 0) + _whole(tender.get("pence"), "tender", 1)
    return TapeSale(str(record["store"]), _whole(record["till"], "till", 1), str(record["sale"]), str(record["at"]),
                    tuple(lines), tenders, _whole(record["change"], "change"))


def read_tape(path: Path) -> Tape:
    path = Path(path)
    name = TAPE_NAME.match(path.name)
    if not name:
        raise ValueError(f"{path.name} is not named like a tape")
    tape = Tape(path, name["store"], date.fromisoformat(name["day"]))
    with open(path, encoding="utf-8") as handle:
        for line_no, text in enumerate(handle, start=1):
            if not text.strip():
                continue
            try:
                sale = check_record(json.loads(text))
                if sale.store != tape.store:
                    raise TapeRecordError(f"sale from store {sale.store} on {tape.store}'s tape")
                if not sale.at.startswith(tape.day.isoformat()):
                    raise TapeRecordError(f"sale dated {sale.at} on the tape for {tape.day.isoformat()}")
            except (json.JSONDecodeError, TapeRecordError) as exc:
                tape.quarantined.append(Quarantined(path.name, line_no, str(exc)))
                continue
            tape.sales.append(sale)
    return tape
