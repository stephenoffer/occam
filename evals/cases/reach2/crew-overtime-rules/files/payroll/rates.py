"""Base hourly rates per worker, and the overtime multiplier from the site agreement."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from common.csvio import CsvError, read_rows
from common.money import parse_money

OVERTIME_MULTIPLIER = Decimal("1.5")
GRADES = {"labourer", "operative", "skilled", "supervisor", "apprentice"}


@dataclass(frozen=True)
class Rate:
    worker_id: str
    name: str
    grade: str
    base_hourly: Decimal

    @property
    def overtime_hourly(self) -> Decimal:
        return self.base_hourly * OVERTIME_MULTIPLIER


def load_rates(path: str | Path) -> dict[str, Rate]:
    rates: dict[str, Rate] = {}
    for row in read_rows(path, ["worker_id", "name", "grade", "base_hourly"]):
        where = f"{path}:{row['_line']}"
        if row["grade"] not in GRADES:
            raise CsvError(f"{where}: unknown grade {row['grade']!r}")
        if row["worker_id"] in rates:
            raise CsvError(f"{where}: {row['worker_id']} listed twice")
        try:
            base = parse_money(row["base_hourly"])
        except ValueError as exc:
            raise CsvError(f"{where}: {exc}") from exc
        if base <= 0:
            raise CsvError(f"{where}: base rate must be positive")
        rates[row["worker_id"]] = Rate(row["worker_id"], row["name"], row["grade"], base)
    return rates
