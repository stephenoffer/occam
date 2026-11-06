"""The figures the ops desk publishes."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from statistics import fmean

from .events import HIGH_WATER, LOW_WATER, TideEvent, local_day
from .readings import Reading


def daily_extrema(readings: Iterable[Reading], tz_name: str) -> dict[date, tuple[Reading, Reading]]:
    """Return the highest and lowest reading of each local day.

    Parameters
    ----------
    readings : Iterable[Reading]
        One station's readings.
    tz_name : str
        IANA timezone name of the station.

    Returns
    -------
    dict[datetime.date, tuple[Reading, Reading]]
        The lowest and highest reading of each day that has any.

    Examples
    --------
    >>> from datetime import UTC, datetime
    >>> low = Reading("HLX", datetime(2026, 7, 1, 12, tzinfo=UTC), 0.5)
    >>> high = Reading("HLX", datetime(2026, 7, 1, 18, tzinfo=UTC), 2.5)
    >>> lowest, highest = daily_extrema([low, high], "America/Halifax")[date(2026, 7, 1)]
    >>> lowest.level_m, highest.level_m
    (0.5, 2.5)
    """
    days: dict[date, list[Reading]] = {}
    for reading in readings:
        days.setdefault(local_day(reading.observed_at, tz_name), []).append(reading)
    return {
        day: (
            min(day_readings, key=lambda reading: reading.level_m),
            max(day_readings, key=lambda reading: reading.level_m),
        )
        for day, day_readings in days.items()
    }


def _mean_level_m(events: Sequence[TideEvent], kind: str) -> float:
    levels = [event.level_m for event in events if event.kind == kind]
    if not levels:
        raise ValueError(f"no {kind} events")
    return fmean(levels)


def mean_high_water(events: Sequence[TideEvent]) -> float:
    """Return the mean level of the high waters.

    Parameters
    ----------
    events : Sequence[TideEvent]
        Tide events from one station.

    Returns
    -------
    float
        Mean high water, in metres.

    Raises
    ------
    ValueError
        If there are no high waters.

    Examples
    --------
    >>> from datetime import UTC, datetime
    >>> at = datetime(2026, 7, 1, tzinfo=UTC)
    >>> events = [TideEvent("HLX", HIGH_WATER, at, 2.0), TideEvent("HLX", HIGH_WATER, at, 3.0)]
    >>> mean_high_water(events)
    2.5
    """
    return _mean_level_m(events, HIGH_WATER)


def mean_low_water(events: Sequence[TideEvent]) -> float:
    """Return the mean level of the low waters.

    Parameters
    ----------
    events : Sequence[TideEvent]
        Tide events from one station.

    Returns
    -------
    float
        Mean low water, in metres.

    Raises
    ------
    ValueError
        If there are no low waters.

    Examples
    --------
    >>> from datetime import UTC, datetime
    >>> at = datetime(2026, 7, 1, tzinfo=UTC)
    >>> mean_low_water([TideEvent("HLX", LOW_WATER, at, 0.5)])
    0.5
    """
    return _mean_level_m(events, LOW_WATER)


def mean_tidal_range(events: Sequence[TideEvent]) -> float:
    """Return the difference between mean high water and mean low water.

    Parameters
    ----------
    events : Sequence[TideEvent]
        Tide events from one station.

    Returns
    -------
    float
        Mean tidal range, in metres.

    Examples
    --------
    >>> from datetime import UTC, datetime
    >>> at = datetime(2026, 7, 1, tzinfo=UTC)
    >>> events = [TideEvent("HLX", HIGH_WATER, at, 2.0), TideEvent("HLX", LOW_WATER, at, 0.5)]
    >>> mean_tidal_range(events)
    1.5
    """
    return mean_high_water(events) - mean_low_water(events)
