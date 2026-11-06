"""Loads the adjustment schedule and applies the plugins it names."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Final, Protocol, cast

from tidewater.domain.adjustments.context import AdjustmentContext

SCHEDULE: Final = Path(__file__).parent / "adjustments.toml"


class AdjustmentPlugin(Protocol):
    def compute(self, context: AdjustmentContext, params: Mapping[str, str]) -> Decimal: ...


@dataclass(frozen=True)
class ScheduledAdjustment:
    code: str
    plugin: str
    lanes: tuple[str, ...]
    params: tuple[tuple[str, str], ...]

    def applies_to(self, lane: str) -> bool:
        return "*" in self.lanes or lane in self.lanes


@dataclass(frozen=True)
class AdjustmentLine:
    code: str
    amount: Decimal


@lru_cache(maxsize=1)
def schedule() -> tuple[ScheduledAdjustment, ...]:
    entries = tomllib.loads(SCHEDULE.read_text())["adjustment"]
    return tuple(
        ScheduledAdjustment(entry["code"], entry["plugin"], tuple(entry["lanes"]), tuple(entry["params"].items()))
        for entry in entries
    )


def apply_adjustments(lane: str, currency: str, subtotal: Decimal, as_of: date) -> list[AdjustmentLine]:
    context = AdjustmentContext(lane, currency, subtotal, as_of)
    lines = []
    for entry in schedule():
        if entry.applies_to(lane):
            plugin = cast(AdjustmentPlugin, import_module(entry.plugin))
            lines.append(AdjustmentLine(entry.code, plugin.compute(context, dict(entry.params))))
    return lines
