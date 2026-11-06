"""Month-to-date tide figures for every station. Cron runs this file as a script."""

from __future__ import annotations

import argparse
import calendar
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path

from tidekit.datum import reduce_to_chart_datum
from tidekit.events import find_turning_points
from tidekit.readings import load_readings, readings_between, readings_for_station
from tidekit.summary import mean_high_water, mean_low_water


def month_bounds(day: date) -> tuple[date, date]:
    """Return the first and last dates of the month a date falls in.

    Parameters
    ----------
    day : datetime.date
        Any date in the month.

    Returns
    -------
    tuple[datetime.date, datetime.date]
        The first and last dates of that month.

    Examples
    --------
    >>> month_bounds(date(2026, 2, 14))
    (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
    """
    _, last = calendar.monthrange(day.year, day.month)
    return day.replace(day=1), day.replace(day=last)


def main(argv: Sequence[str] | None = None) -> int:
    """Print each station's month-to-date figures.

    Parameters
    ----------
    argv : Sequence[str], optional
        Command line arguments, defaulting to the process's own.

    Returns
    -------
    int
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--offsets", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    offsets_m = json.loads(args.offsets.read_text())
    first_day, last_day = month_bounds(args.day)
    start = datetime.combine(first_day, time.min, tzinfo=UTC)
    end = datetime.combine(last_day, time.max, tzinfo=UTC)
    readings = readings_between(load_readings([args.export]), start, end)
    for station in sorted(offsets_m):
        station_readings = readings_for_station(readings, station)
        events = find_turning_points(reduce_to_chart_datum(station_readings, offsets_m))
        high_water_m = mean_high_water(events)
        low_water_m = mean_low_water(events)
        print(f"{station} MHW={high_water_m:.2f} MLW={low_water_m:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
