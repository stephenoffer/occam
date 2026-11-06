"""Exchange rates. Rates are published per US dollar and crossed through it."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Final

from tidewater.core.errors import RateUnavailable

DATA: Final = Path(__file__).parent / "data"
PIVOT: Final = "USD"
RATE_PLACES: Final = Decimal("0.000001")


@dataclass(frozen=True)
class PublishedRate:
    effective_from: date
    currency: str
    per_usd: Decimal


@lru_cache(maxsize=1)
def _published() -> tuple[PublishedRate, ...]:
    with open(DATA / "fx_rates.csv", newline="") as handle:
        return tuple(
            PublishedRate(date.fromisoformat(row["effective_from"]), row["currency"], Decimal(row["per_usd"]))
            for row in csv.DictReader(handle)
        )


@lru_cache(maxsize=1)
def _contract() -> dict[str, Decimal]:
    with open(DATA / "contract_rates.csv", newline="") as handle:
        return {row["currency"]: Decimal(row["per_usd"]) for row in csv.DictReader(handle)}


def currencies() -> tuple[str, ...]:
    return (PIVOT, *sorted({row.currency for row in _published()}))


def is_known_currency(code: str) -> bool:
    return code in currencies()


def _per_usd_on(currency: str, as_of: date) -> Decimal:
    if currency == PIVOT:
        return Decimal(1)
    rows = [row for row in _published() if row.currency == currency and row.effective_from <= as_of]
    if not rows:
        raise RateUnavailable(f"no rate for {currency} published by {as_of}")
    return max(rows, key=lambda row: row.effective_from).per_usd


def _crossed(base_per_usd: Decimal, quote_per_usd: Decimal) -> Decimal:
    return (quote_per_usd / base_per_usd).quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


def spot_rate(base: str, quote: str, as_of: date) -> Decimal:
    """Units of `quote` for one `base`, at the rate in force on `as_of`."""
    return _crossed(_per_usd_on(base, as_of), _per_usd_on(quote, as_of))


def contract_rate(base: str, quote: str) -> Decimal:
    """Units of `quote` for one `base`, at the fixed rate in the annual carrier contract."""
    table = _contract()
    try:
        base_per_usd = Decimal(1) if base == PIVOT else table[base]
        quote_per_usd = Decimal(1) if quote == PIVOT else table[quote]
    except KeyError as exc:
        raise RateUnavailable(f"no contract rate for {exc.args[0]}") from None
    return _crossed(base_per_usd, quote_per_usd)
