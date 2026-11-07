"""python -m catalog: catalogue maintenance for store managers."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from catalog.departments import department_name
from catalog.price_changes import apply_price_changes, read_price_changes
from catalog.products import DEFAULT_CATALOG, load_catalog, write_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m catalog")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="list products, optionally for one department")
    show.add_argument("--department")
    prices = commands.add_parser("apply-prices", help="apply a price-change file")
    prices.add_argument("changes")
    prices.add_argument("--on", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    catalog = load_catalog(args.catalog)
    if args.command == "show":
        products = catalog.in_department(args.department.upper()) if args.department else catalog.all()
        for product in products:
            print(f"{product.sku:<16} {product.price_pence / 100:>8.2f}  {department_name(product.department):<20} {product.description}")
        return 0
    updated, missing = apply_price_changes(catalog, read_price_changes(args.changes), args.on)
    write_catalog(updated, args.catalog)
    for sku in missing:
        print(f"not in catalogue: {sku}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
