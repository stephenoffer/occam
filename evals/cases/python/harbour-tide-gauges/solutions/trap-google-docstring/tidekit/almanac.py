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

    Args:
        station: Station code.
        readings: Gauge readings, which may include other stations.
        offsets_m: How far each station's gauge zero sits above chart datum, in metres.
        tz_name: IANA timezone name of the station. Days are local days there.
        first_day: First day to list.
        last_day: Last day to list, included.

    Returns:
        Every day in the range, mapped to its tide events in time order.

    Example:
        >>> tide_calendar("HLX", [], {"HLX": 0.5}, "UTC", date(2026, 7, 1), date(2026, 7, 1))
        {datetime.date(2026, 7, 1): []}
    """
    station_readings = readings_for_station(readings, station)
    events = find_turning_points(reduce_to_chart_datum(station_readings, offsets_m))
    day_count = (last_day - first_day).days + 1
    days: dict[date, list[TideEvent]] = {
        first_day + timedelta(days=number): [] for number in range(day_count)
    }
    for event in events:
        day = local_day(event.occurred_at, tz_name)
        if day in days:
            days[day].append(event)
    return days
