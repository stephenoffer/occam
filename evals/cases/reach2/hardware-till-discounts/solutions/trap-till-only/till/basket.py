"""A basket being rung up: priced lines, their discounts and totals."""

from __future__ import annotations

from dataclasses import dataclass, field

from catalog.products import Catalog

MAX_QTY = 999
DISCOUNT_REASONS = ("STAFF", "PROMO", "DAMAGED")


class BasketError(ValueError):
    """A basket the till can't ring: bad quantity, unknown product and so on."""


@dataclass(frozen=True)
class Line:
    sku: str
    description: str
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
        """What the customer pays for the line, after any discount."""
        return self.gross_pence - self.discount_pence


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


def apply_discount(line: Line, discount: object) -> Line:
    """A discount is {"pence": int, "reason": one of DISCOUNT_REASONS}, taken off the line's total."""
    if not isinstance(discount, dict):
        raise BasketError(f"{line.sku}: a discount needs pence and a reason")
    pence, reason = discount.get("pence"), discount.get("reason")
    if reason not in DISCOUNT_REASONS:
        raise BasketError(f"{line.sku}: discount reason must be one of {', '.join(DISCOUNT_REASONS)}")
    if not isinstance(pence, int) or isinstance(pence, bool) or not 1 <= pence <= line.gross_pence:
        raise BasketError(f"{line.sku}: discount must be a whole number of pence from 1 to the line's {line.gross_pence}")
    return Line(line.sku, line.description, line.department, line.qty, line.unit_pence, pence, reason)


def build_basket(catalog: Catalog, entries: list[dict]) -> Basket:
    """Price the `lines` of a basket file. Each entry is {"sku": ..., "qty": ..., "discount": {...}}."""
    basket = Basket()
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or "sku" not in entry:
            raise BasketError(f"line {number}: needs a sku")
        line = price_line(catalog, str(entry["sku"]), entry.get("qty", 1))
        if entry.get("discount") is not None:
            line = apply_discount(line, entry["discount"])
        basket.add(line)
    if basket.is_empty():
        raise BasketError("the basket is empty")
    return basket
