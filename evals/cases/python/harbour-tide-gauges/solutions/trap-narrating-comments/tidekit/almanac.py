"""Day-by-day tide events for a station."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from .datum import reduce_to_chart_datum
from .events import TideEvent, find_turning_points, local_day
from .readings import Reading, readings_for_station


def tide_calendar(  # noqa: PLR0913 -- the ops notebook passes all six positionally
    station: str,
    readings: Sequence[Reading],
    offsets_m: Mapping[str, float],
    tz_name: str,
    first_day: date,
    last_day: date,
) -> dict[date, list[TideEvent]]:
    """List every high water and low water at a station, day by day.

    Parameters
    ----------
    station : str
        Station code.
    readings : Sequence[Reading]
        Gauge readings, which may include other stations.
    offsets_m : Mapping[str, float]
        How far each station's gauge zero sits above chart datum, in metres.
    tz_name : str
        IANA timezone name of the station. Days are local days there.
    first_day : datetime.date
        First day to list.
    last_day : datetime.date
        Last day to list, included.

    Returns
    -------
    dict[datetime.date, list[TideEvent]]
        Every day in the range, mapped to its tide events in time order, with levels relative to
        chart datum. A day with no events maps to an empty list.

    Examples
    --------
    >>> from datetime import UTC, datetime
    >>> levels = [1.0, 2.0, 1.0, 0.5, 1.0]
    >>> readings = [
    ...     Reading("HLX", datetime(2026, 7, 1, 12 + hour, tzinfo=UTC), level_m)
    ...     for hour, level_m in enumerate(levels)
    ... ]
    >>> calendar = tide_calendar(
    ...     "HLX", readings, {"HLX": 0.5}, "America/Halifax", date(2026, 7, 1), date(2026, 7, 2)
    ... )
    >>> [(event.kind, event.level_m) for event in calendar[date(2026, 7, 1)]]
    [('high_water', 1.5), ('low_water', 0.0)]
    >>> calendar[date(2026, 7, 2)]
    []
    """
    # Get the readings for this station
    station_readings = readings_for_station(readings, station)
    events = find_turning_points(reduce_to_chart_datum(station_readings, offsets_m))
    # Initialize the result dict
    day_count = (last_day - first_day).days + 1
    days: dict[date, list[TideEvent]] = {
        first_day + timedelta(days=number): [] for number in range(day_count)
    }
    # Loop over the events
    for event in events:
        day = local_day(event.occurred_at, tz_name)
        if day in days:
            days[day].append(event)
    return days
