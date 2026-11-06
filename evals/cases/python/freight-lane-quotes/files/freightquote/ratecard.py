"""The quarterly rate card: per-mode rates and the lanes the desk sells."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .codec import decode
from .errors import RateCardError
from .models import Lane, Mode


@dataclass(frozen=True)
class ModeRates:
    """What one transport mode charges."""

    per_km: Decimal
    per_kg: Decimal
    minimum_charge: Decimal


@dataclass(frozen=True)
class RateCard:
    """One published quarter of rates and lanes."""

    version: str
    rates: dict[Mode, ModeRates]
    lanes: dict[str, Lane]

    def lane(self, code: str) -> Lane:
        """Return the lane with this code, or raise RateCardError."""
        try:
            return self.lanes[code]
        except KeyError:
            raise RateCardError(f"no lane {code!r} on rate card {self.version}") from None


def _parse_rates(raw: dict[str, Any]) -> ModeRates:
    return ModeRates(
        per_km=Decimal(raw["per_km"]),
        per_kg=Decimal(raw["per_kg"]),
        minimum_charge=Decimal(raw["minimum_charge"]),
    )


def _parse_lane(raw: dict[str, Any]) -> Lane:
    return Lane(
        code=raw["code"],
        origin=raw["origin"],
        destination=raw["destination"],
        mode=Mode(raw["mode"]),
        distance_km=int(raw["distance_km"]),
        max_weight_kg=Decimal(raw["max_weight_kg"]),
        max_volume_m3=Decimal(raw["max_volume_m3"]),
        carries_dangerous_goods=bool(raw.get("carries_dangerous_goods", False)),
    )


def validate_rate_card(card: RateCard) -> bool:
    """Return True for a usable card, or raise RateCardError naming the first problem."""
    for mode in Mode:
        if mode not in card.rates:
            raise RateCardError(f"rate card {card.version} has no rates for {mode.value}")
    for mode, rates in card.rates.items():
        if rates.per_km <= 0 or rates.per_kg <= 0:
            raise RateCardError(f"rate card {card.version} has a non-positive {mode.value} rate")
    for lane in card.lanes.values():
        if lane.distance_km <= 0:
            raise RateCardError(f"lane {lane.code} has a non-positive distance")
        if lane.max_weight_kg <= 0 or lane.max_volume_m3 <= 0:
            raise RateCardError(f"lane {lane.code} has a non-positive capacity")
    return True


def load_rate_card(path: Path) -> RateCard:
    """Read and validate a rate card, raising RateCardError if it can't be used."""
    try:
        raw = decode(path.read_text(encoding="utf-8"))
        card = RateCard(
            version=str(raw["version"]),
            rates={Mode(name): _parse_rates(rates) for name, rates in raw["rates"].items()},
            lanes={lane["code"]: _parse_lane(lane) for lane in raw["lanes"]},
        )
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
        raise RateCardError(f"cannot load rate card {path}: {exc}") from exc
    validate_rate_card(card)
    return card
