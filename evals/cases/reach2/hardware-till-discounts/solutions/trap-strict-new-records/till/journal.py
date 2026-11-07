"""The sales journal: one JSON line per completed sale, one file per trading day.

    <data>/journal/2026-11-09.jsonl

A record looks like

    {"v": 2, "store": "BRH01", "till": 1, "sale": "BRH01-1-261109-0001", "at": "2026-11-09T09:14:03",
     "lines": [{"sku": "PNT-1L-WHT", "dept": "PNT", "qty": 2, "unit": 1299,
                "discount": {"pence": 40, "reason": "STAFF"}}],
     "tenders": [{"type": "cash", "pence": 3000}], "change": 442}

A line only carries `discount` when it was discounted.

The journal is append-only. Nothing rewrites a line once it's written; a mistake is put right by
ringing a refund, never by editing the file. At close of day the file goes to the outbox
(see endofday.py).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from till.tender import Tender

JOURNAL_VERSION = 2
READABLE_VERSIONS = {JOURNAL_VERSION}


class JournalError(ValueError):
    """A journal line the till can't read."""


@dataclass(frozen=True)
class RecordLine:
    sku: str
    department: str
    qty: int
    unit_pence: int
    discount_pence: int = 0
    discount_reason: str | None = None

    @property
    def gross_pence(self) -> int:
        return self.qty * self.unit_pence

    @property
    def total_pence(self) -> int:
        return self.gross_pence - self.discount_pence


@dataclass(frozen=True)
class SaleRecord:
    store: str
    till: int
    sale: str
    at: datetime
    lines: tuple[RecordLine, ...]
    tenders: tuple[Tender, ...]
    change_pence: int

    @property
    def total_pence(self) -> int:
        return sum(line.total_pence for line in self.lines)

    @property
    def day(self) -> date:
        return self.at.date()


def journal_path(data_dir: Path, day: date) -> Path:
    return Path(data_dir) / "journal" / f"{day.isoformat()}.jsonl"


def to_record(sale: SaleRecord) -> dict:
    return {
        "v": JOURNAL_VERSION,
        "store": sale.store,
        "till": sale.till,
        "sale": sale.sale,
        "at": sale.at.isoformat(timespec="seconds"),
        "lines": [_line_record(l) for l in sale.lines],
        "tenders": [{"type": t.type, "pence": t.pence} for t in sale.tenders],
        "change": sale.change_pence,
    }


def _line_record(line: RecordLine) -> dict:
    record = {"sku": line.sku, "dept": line.department, "qty": line.qty, "unit": line.unit_pence}
    if line.discount_pence:
        record["discount"] = {"pence": line.discount_pence, "reason": line.discount_reason}
    return record


def _line_from_record(record: dict) -> RecordLine:
    discount = record.get("discount") or {}
    return RecordLine(record["sku"], record["dept"], int(record["qty"]), int(record["unit"]),
                      int(discount.get("pence", 0)), discount.get("reason"))


def from_record(record: dict) -> SaleRecord:
    if record.get("v") not in READABLE_VERSIONS:
        raise JournalError(f"journal version {record.get('v')!r} is not one this till reads")
    try:
        return SaleRecord(
            store=record["store"],
            till=int(record["till"]),
            sale=record["sale"],
            at=datetime.fromisoformat(record["at"]),
            lines=tuple(_line_from_record(l) for l in record["lines"]),
            tenders=tuple(Tender(t["type"], int(t["pence"])) for t in record["tenders"]),
            change_pence=int(record["change"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalError(f"malformed journal record: {exc}") from None


def append(data_dir: Path, sale: SaleRecord) -> Path:
    path = journal_path(data_dir, sale.day)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(to_record(sale), separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def read_day(data_dir: Path, day: date) -> list[SaleRecord]:
    path = journal_path(data_dir, day)
    if not path.exists():
        return []
    sales = []
    with open(path, encoding="utf-8") as handle:
        for number, text in enumerate(handle, start=1):
            if not text.strip():
                continue
            try:
                sales.append(from_record(json.loads(text)))
            except (json.JSONDecodeError, JournalError) as exc:
                raise JournalError(f"{path.name} line {number}: {exc}") from None
    return sales


def next_sale_id(data_dir: Path, store: str, till: int, day: date) -> str:
    count = len(read_day(data_dir, day))
    return f"{store}-{till}-{day:%y%m%d}-{count + 1:04d}"
