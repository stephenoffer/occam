"""Ringing a sale from a basket file.

A basket file is what the till front end hands over when the cashier presses PAY:

    {"at": "2026-11-09T09:14:03",
     "lines": [{"sku": "PNT-1L-WHT", "qty": 2}, {"sku": "FIX-PLUG-RED"}],
     "tenders": [{"type": "card", "pence": 2000}, {"type": "cash", "pence": 1000}]}

`qty` defaults to 1 and `at` to now. Ringing prices the lines from the catalogue, checks the
payment, writes the sale to the journal and returns the receipt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from catalog.products import Catalog
from till import journal
from till.basket import Basket, BasketError, build_basket
from till.receipt import render_receipt
from till.settings import load_settings
from till.tender import TenderError, parse_tenders, settle


class RingError(ValueError):
    """The sale was not rung; nothing was written."""


@dataclass(frozen=True)
class Rung:
    record: journal.SaleRecord
    basket: Basket
    receipt: str


def read_basket_file(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RingError(f"can't read basket {path}: {exc}") from None
    if not isinstance(data, dict):
        raise RingError("a basket file holds one JSON object")
    return data


def ring(data_dir: Path, basket_data: dict, catalog: Catalog) -> Rung:
    settings = load_settings(data_dir)
    try:
        basket = build_basket(catalog, basket_data.get("lines", []))
        tenders = parse_tenders(basket_data.get("tenders", []))
        change = settle(basket.total_pence, tenders)
    except (BasketError, TenderError) as exc:
        raise RingError(str(exc)) from None
    at = datetime.fromisoformat(basket_data["at"]) if basket_data.get("at") else datetime.now().replace(microsecond=0)
    record = journal.SaleRecord(
        store=settings.store,
        till=settings.number,
        sale=journal.next_sale_id(data_dir, settings.store, settings.number, at.date()),
        at=at,
        lines=tuple(journal.RecordLine(l.sku, l.department, l.qty, l.unit_pence) for l in basket.lines),
        tenders=tuple(tenders),
        change_pence=change,
    )
    journal.append(data_dir, record)
    receipt = render_receipt(store_name=settings.store_name, till=settings.number, sale=record.sale, at=at,
                             basket=basket, tenders=tenders, change_pence=change)
    return Rung(record, basket, receipt)
