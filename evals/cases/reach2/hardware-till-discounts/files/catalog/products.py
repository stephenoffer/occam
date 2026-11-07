"""Loading and looking up products.

The catalogue is a CSV kept in `catalog/data/products.csv`, regenerated each week from the buying
team's spreadsheet. Prices are whole pence, VAT included, as everywhere else (ADR 0001).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from catalog.departments import DEPARTMENTS

DEFAULT_CATALOG = Path(__file__).parent / "data" / "products.csv"


class ProductNotFound(KeyError):
    """Raised when a SKU isn't in the catalogue."""


@dataclass(frozen=True)
class Product:
    sku: str
    description: str
    department: str
    price_pence: int


class Catalog:
    def __init__(self, products: dict[str, Product]):
        self._products = products

    def __len__(self) -> int:
        return len(self._products)

    def __contains__(self, sku: str) -> bool:
        return sku.upper() in self._products

    def get(self, sku: str) -> Product:
        try:
            return self._products[sku.upper()]
        except KeyError:
            raise ProductNotFound(sku) from None

    def in_department(self, code: str) -> list[Product]:
        return sorted((p for p in self._products.values() if p.department == code), key=lambda p: p.sku)

    def all(self) -> list[Product]:
        return sorted(self._products.values(), key=lambda p: p.sku)


def parse_row(row: dict[str, str], line: int) -> Product:
    sku = row["sku"].strip().upper()
    if not sku:
        raise ValueError(f"line {line}: empty sku")
    department = row["department"].strip().upper()
    if department not in DEPARTMENTS:
        raise ValueError(f"line {line}: unknown department {department!r}")
    price = int(row["price_pence"])
    if price < 0:
        raise ValueError(f"line {line}: negative price")
    return Product(sku, row["description"].strip(), department, price)


def load_catalog(path: Path | str = DEFAULT_CATALOG) -> Catalog:
    products: dict[str, Product] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            product = parse_row(row, line)
            if product.sku in products:
                raise ValueError(f"line {line}: duplicate sku {product.sku}")
            products[product.sku] = product
    return Catalog(products)


def write_catalog(catalog: Catalog, path: Path | str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sku", "description", "department", "price_pence"])
        for product in catalog.all():
            writer.writerow([product.sku, product.description, product.department, product.price_pence])
