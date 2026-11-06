"""Reducing water levels to chart datum."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace

from .readings import Reading

Corrector = Callable[[float], float]


def datum_correctors(offsets_m: Mapping[str, float]) -> dict[str, Corrector]:
    """Build a function per station that reduces a level to chart datum.

    Parameters
    ----------
    offsets_m : Mapping[str, float]
        How far each station's gauge zero sits above chart datum, in metres.

    Returns
    -------
    dict[str, Corrector]
        A corrector for each station.

    Examples
    --------
    >>> correctors = datum_correctors({"HLX": 0.35})
    >>> round(correctors["HLX"](2.0), 2)
    1.65
    """
    correctors: dict[str, Corrector] = {}
    for station, offset_m in offsets_m.items():
        correctors[station] = lambda level_m, offset_m=offset_m: level_m - offset_m
    return correctors


def reduce_to_chart_datum(
    readings: Iterable[Reading], offsets_m: Mapping[str, float]
) -> list[Reading]:
    """Express readings relative to chart datum.

    Parameters
    ----------
    readings : Iterable[Reading]
        Readings relative to their gauge zeros.
    offsets_m : Mapping[str, float]
        How far each station's gauge zero sits above chart datum, in metres.

    Returns
    -------
    list[Reading]
        The readings in the same order, with reduced levels.

    Raises
    ------
    KeyError
        If a reading's station has no offset.

    Examples
    --------
    >>> from datetime import UTC, datetime
    >>> reading = Reading("HLX", datetime(2026, 7, 1, tzinfo=UTC), 2.0)
    >>> reduce_to_chart_datum([reading], {"HLX": 0.5})[0].level_m
    1.5
    """
    correctors = datum_correctors(offsets_m)
    return [
        replace(reading, level_m=correctors[reading.station](reading.level_m))
        for reading in readings
    ]
