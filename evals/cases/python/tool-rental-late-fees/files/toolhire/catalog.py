"""What we hire out."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    sku: str
    name: str
    tool_class: str
    deposit_cents: int
    daily_cents: int


CATALOG = {
    tool.sku: tool
    for tool in (
        Tool("SDS-DRILL", "SDS hammer drill", "small", 5000, 1800),
        Tool("ORBITAL", "Orbital sander", "small", 4000, 1200),
        Tool("TILE-SAW", "Wet tile saw", "medium", 12000, 3500),
        Tool("COMPACTOR", "Plate compactor", "medium", 15000, 4800),
        Tool("TOWER", "Scaffold tower", "heavy", 30000, 7500),
        Tool("MINI-DIGGER", "1.5 tonne mini digger", "heavy", 60000, 16500),
    )
}


def lookup(sku: str) -> Tool:
    try:
        return CATALOG[sku]
    except KeyError:
        raise KeyError(f"no such tool: {sku}") from None


def in_class(tool_class: str) -> list[Tool]:
    return sorted((tool for tool in CATALOG.values() if tool.tool_class == tool_class), key=lambda tool: tool.sku)
