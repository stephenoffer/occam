"""Whether a lane can carry a shipment."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from .models import Lane, Shipment

Rule = Callable[[Shipment, Lane], bool]

AIR_MAX_KG_PER_UNIT = Decimal("250")
RAIL_MIN_WEIGHT_KG = Decimal("500")


def within_weight_limit(shipment: Shipment, lane: Lane) -> bool:
    """Return whether the shipment's weight fits the lane."""
    return shipment.weight_kg <= lane.max_weight_kg


def within_volume_limit(shipment: Shipment, lane: Lane) -> bool:
    """Return whether the shipment's volume fits the lane."""
    return shipment.volume_m3 <= lane.max_volume_m3


def dangerous_goods_allowed(shipment: Shipment, lane: Lane) -> bool:
    """Return whether the lane may carry the shipment's dangerous goods class, if it has one."""
    return shipment.dg_class is None or lane.carries_dangerous_goods


def meets_rail_minimum(shipment: Shipment, lane: Lane) -> bool:
    """Return whether the shipment is heavy enough to be worth a rail booking."""
    return shipment.weight_kg >= RAIL_MIN_WEIGHT_KG


def within_air_unit_weight(shipment: Shipment, lane: Lane) -> bool:
    """Return whether each unit is light enough to be loaded on an aircraft by hand."""
    return shipment.weight_kg / shipment.units <= AIR_MAX_KG_PER_UNIT


_COMMON_RULES: tuple[Rule, ...] = (
    within_weight_limit,
    within_volume_limit,
    dangerous_goods_allowed,
)

RULES_BY_MODE: dict[str, tuple[Rule, ...]] = {
    "road": _COMMON_RULES,
    "rail": (*_COMMON_RULES, meets_rail_minimum),
    "air": (*_COMMON_RULES, within_air_unit_weight),
}


def rules_for(lane: Lane) -> tuple[Rule, ...]:
    """Return the rules that apply to a lane's transport mode."""
    return RULES_BY_MODE.get(lane.mode.value, ())


def is_eligible(shipment: Shipment, lane: Lane) -> bool:
    """Return whether every rule for the lane's mode accepts the shipment."""
    return all(rule(shipment, lane) for rule in rules_for(lane))
