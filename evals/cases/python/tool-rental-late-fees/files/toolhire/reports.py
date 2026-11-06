"""Monthly back office reporting."""

from collections.abc import Iterable

from toolhire.models import Settlement


def late_fee_summary(settlements: Iterable[Settlement]) -> dict[str, int]:
    summary = {"returns": 0, "late_returns": 0, "late_fee_cents": 0, "damage_cents": 0, "released_cents": 0}
    for settlement in settlements:
        summary["returns"] += 1
        summary["late_returns"] += 1 if settlement.late_days else 0
        summary["late_fee_cents"] += settlement.late_fee_cents
        summary["damage_cents"] += settlement.damage_cents
        summary["released_cents"] += settlement.released_cents
    return summary


def worst_offenders(settlements: Iterable[Settlement], limit: int = 3) -> list[str]:
    ranked = sorted(settlements, key=lambda s: (-s.late_days, s.rental_id))
    return [settlement.rental_id for settlement in ranked[:limit] if settlement.late_days]
