"""Tide events: the high waters and low waters in a series of readings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .readings import Reading

HIGH_WATER = "high_water"
LOW_WATER = "low_water"


@dataclass(frozen=True)
class TideEvent:
    """A high water or low water at a station.

    Attributes
    ----------
    station : str
        Station code.
    kind : str
        Either ``HIGH_WATER`` or ``LOW_WATER``.
    occurred_at : datetime.datetime
        When the reading at the turning point was taken.
    level_m : float
        Water level at the turning point, in metres.
    """

    station: str
    kind: str
    occurred_at: datetime
    level_m: float


def find_turning_points(readings: Sequence[Reading]) -> list[TideEvent]:
    """Find the high waters and low waters in one station's readings.

    A turning point is a reading strictly above or strictly below both of its neighbours, so the
    first and last readings can't be one.

    Parameters
    ----------
    readings : Sequence[Reading]
        One station's readings, in time order.

    Returns
    -------
    list[TideEvent]
        The tide events, in time order.

    Raises
    ------
    ValueError
        If the readings come from more than one station.

    Examples
    --------
    >>> from datetime import UTC
    >>> levels = [1.0, 2.0, 1.0, 0.5, 1.0]
    >>> readings = [
    ...     Reading("HLX", datetime(2026, 7, 1, hour, tzinfo=UTC), level_m)
    ...     for hour, level_m in enumerate(levels)
    ... ]
    >>> [(event.kind, event.level_m) for event in find_turning_points(readings)]
    [('high_water', 2.0), ('low_water', 0.5)]
    """
    stations = {reading.station for reading in readings}
    if len(stations) > 1:
        raise ValueError(f"readings from several stations: {sorted(stations)}")
    events: list[TideEvent] = []
    for before, reading, after in zip(readings, readings[1:], readings[2:], strict=False):
        if before.level_m < reading.level_m > after.level_m:
            kind = HIGH_WATER
        elif before.level_m > reading.level_m < after.level_m:
            kind = LOW_WATER
        else:
            continue
        events.append(TideEvent(reading.station, kind, reading.observed_at, reading.level_m))
    return events


def local_day(moment: datetime, tz_name: str) -> date:
    """Return the date a moment falls on in a station's timezone.

    Parameters
    ----------
    moment : datetime.datetime
        A timezone-aware moment.
    tz_name : str
        IANA timezone name of the station.

    Returns
    -------
    datetime.date
        The local date.

    Examples
    --------
    >>> from datetime import UTC
    >>> local_day(datetime(2026, 7, 1, 2, tzinfo=UTC), "America/Halifax")
    datetime.date(2026, 6, 30)
    """
    return moment.astimezone(ZoneInfo(tz_name)).date()
