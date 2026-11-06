"""The chartering desk's index of the voyage market. Worldscale points, nothing to do with currencies."""

from decimal import Decimal
from typing import Final

_WORLDSCALE_POINTS: Final = {
    ("AG-EAST", 2025): Decimal("61.5"),
    ("AG-EAST", 2026): Decimal("58.0"),
    ("WAF-EAST", 2025): Decimal("74.0"),
    ("WAF-EAST", 2026): Decimal("69.5"),
}


def historic_spot_rate(route: str, year: int) -> Decimal:
    return _WORLDSCALE_POINTS[(route, year)]


def spot_rate_index(route: str, base_year: int, year: int) -> Decimal:
    return historic_spot_rate(route, year) / historic_spot_rate(route, base_year) * Decimal(100)
