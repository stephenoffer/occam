"""Taking a day's sales off stock.

Runs after close of day on the store PC. It reads the till's journal for the day and takes each
line's quantity off stock on hand. Stock can go negative (a product sold before its delivery was
booked in); negative lines are listed so the manager can chase the delivery note.

A marker file stops a day being taken off twice.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from stock.levels import load_levels, save_levels
from till.journal import read_day


def marker(data_dir: Path, day: date) -> Path:
    return Path(data_dir) / "stock-depleted" / day.isoformat()


def deplete_day(data_dir: Path, day: date) -> list[str]:
    """Take the day's sales off stock. Returns the SKUs now below zero."""
    done = marker(data_dir, day)
    if done.exists():
        raise RuntimeError(f"stock for {day.isoformat()} has already been taken off")
    sold: Counter = Counter()
    for sale in read_day(data_dir, day):
        for line in sale.lines:
            sold[line.sku] += line.qty
    levels = load_levels(data_dir)
    for sku, qty in sold.items():
        levels[sku] = levels.get(sku, 0) - qty
    save_levels(data_dir, levels)
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_text("", encoding="utf-8")
    return sorted(sku for sku, on_hand in levels.items() if on_hand < 0)
