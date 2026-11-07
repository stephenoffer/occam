"""Stock on hand, kept per store in `<data>/stock.csv` as `sku,on_hand`."""

from __future__ import annotations

import csv
from pathlib import Path


def stock_path(data_dir: Path) -> Path:
    return Path(data_dir) / "stock.csv"


def load_levels(data_dir: Path) -> dict[str, int]:
    path = stock_path(data_dir)
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["sku"]: int(row["on_hand"]) for row in csv.DictReader(handle)}


def save_levels(data_dir: Path, levels: dict[str, int]) -> None:
    path = stock_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with open(temporary, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sku", "on_hand"])
        for sku in sorted(levels):
            writer.writerow([sku, levels[sku]])
    temporary.replace(path)


def receive_delivery(data_dir: Path, delivery: dict[str, int]) -> dict[str, int]:
    levels = load_levels(data_dir)
    for sku, qty in delivery.items():
        if qty <= 0:
            raise ValueError(f"{sku}: delivered quantity must be positive")
        levels[sku] = levels.get(sku, 0) + qty
    save_levels(data_dir, levels)
    return levels
