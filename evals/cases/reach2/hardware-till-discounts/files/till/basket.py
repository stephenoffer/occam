"""A basket being rung up: priced lines and their totals."""

from __future__ import annotations

from dataclasses import dataclass, field

from catalog.products import Catalog

MAX_QTY = 999


class BasketError(ValueError):
    """A basket the till can't ring: bad quantity, unknown product and so on."""


@dataclass(frozen=True)
class Line:
    sku: str
    description: str
    department: str
    qty: int
    unit_pence: int

    @property
    def total_pence(self) -> int:
        return self.qty * self.unit_pence


@dataclass
class Basket:
    lines: list[Line] = field(default_factory=list)

    def add(self, line: Line) -> None:
        self.lines.append(line)

    @property
    def total_pence(self) -> int:
        return sum(line.total_pence for line in self.lines)

    @property
    def item_count(self) -> int:
        return sum(line.qty for line in self.lines)

    def is_empty(self) -> bool:
        return not self.lines


def price_line(catalog: Catalog, sku: str, qty: int) -> Line:
    if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= MAX_QTY:
        raise BasketError(f"{sku}: quantity must be a whole number from 1 to {MAX_QTY}")
    if sku not in catalog:
        raise BasketError(f"{sku}: not in the catalogue")
    product = catalog.get(sku)
    return Line(product.sku, product.description, product.department, qty, product.price_pence)


def build_basket(catalog: Catalog, entries: list[dict]) -> Basket:
    """Price the `lines` of a basket file. Each entry is {"sku": ..., "qty": ...}."""
    basket = Basket()
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or "sku" not in entry:
            raise BasketError(f"line {number}: needs a sku")
        basket.add(price_line(catalog, str(entry["sku"]), entry.get("qty", 1)))
    if basket.is_empty():
        raise BasketError("the basket is empty")
    return basket
