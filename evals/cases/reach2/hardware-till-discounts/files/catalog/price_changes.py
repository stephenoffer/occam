"""Apply the buying team's price-change file to the catalogue.

A price-change file is a CSV of `sku,new_price_pence,effective`. Changes take effect at the start
of trading on their effective date; a file can carry changes for several dates, and only those due
on or before the date given are applied. Unknown SKUs are reported, not added: new lines come
through the weekly catalogue refresh instead.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from catalog.products import Catalog, Product


@dataclass(frozen=True)
class PriceChange:
    sku: str
    new_price_pence: int
    effective: date


def read_price_changes(path: Path | str) -> list[PriceChange]:
    changes = []
    with open(path, newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            try:
                price = int(row["new_price_pence"])
                effective = date.fromisoformat(row["effective"].strip())
            except (KeyError, ValueError) as exc:
                raise ValueError(f"line {line}: {exc}") from None
            if price <= 0:
                raise ValueError(f"line {line}: price must be positive")
            changes.append(PriceChange(row["sku"].strip().upper(), price, effective))
    return changes


def apply_price_changes(catalog: Catalog, changes: list[PriceChange], on: date) -> tuple[Catalog, list[str]]:
    """Return a new catalogue with the changes due by `on`, and the SKUs that weren't found."""
    products: dict[str, Product] = {p.sku: p for p in catalog.all()}
    missing = []
    for change in sorted(changes, key=lambda c: c.effective):
        if change.effective > on:
            continue
        if change.sku not in products:
            missing.append(change.sku)
            continue
        products[change.sku] = replace(products[change.sku], price_pence=change.new_price_pence)
    return Catalog(products), missing
