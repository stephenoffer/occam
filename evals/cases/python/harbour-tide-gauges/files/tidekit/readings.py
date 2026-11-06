"""Gauge readings and the harbour export they arrive in."""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CM_PER_M = 100.0
READ_ATTEMPTS = 3


@dataclass(frozen=True)
class Reading:
    """One water level from a station's gauge.

    Attributes
    ----------
    station : str
        Station code, such as ``"HLX"``.
    observed_at : datetime.datetime
        When the level was read, timezone-aware.
    level_m : float
        Water level in metres above the gauge zero.
    """

    station: str
    observed_at: datetime
    level_m: float


def reading_from_row(  # noqa: PLR0913 -- one argument per column of the harbour export
    station: str, date_text: str, time_text: str, level_text: str, unit: str, quality: str
) -> Reading | None:
    """Build a reading from one row of the harbour export.

    Parameters
    ----------
    station : str
        Station code.
    date_text : str
        UTC date, as ``YYYY-MM-DD``.
    time_text : str
        UTC time, as ``HH:MM``.
    level_text : str
        Water level in ``unit``.
    unit : str
        Either ``"m"`` or ``"cm"``.
    quality : str
        The gauge's quality flag. Rows flagged ``"suspect"`` are dropped.

    Returns
    -------
    Reading or None
        The reading, or ``None`` for a suspect row.

    Raises
    ------
    ValueError
        If the unit isn't one the export uses.

    Examples
    --------
    >>> reading_from_row("HLX", "2026-07-01", "12:30", "152", "cm", "good").level_m
    1.52
    >>> reading_from_row("HLX", "2026-07-01", "12:30", "152", "cm", "suspect") is None
    True
    """
    if quality == "suspect":
        return None
    if unit not in ("m", "cm"):
        raise ValueError(f"unknown unit {unit!r} for station {station}")
    level = float(level_text)
    observed_at = datetime.fromisoformat(f"{date_text}T{time_text}").replace(tzinfo=UTC)
    return Reading(station, observed_at, level if unit == "m" else level / CM_PER_M)


def _read_with_retry(read: Callable[[], str]) -> str:
    """Call ``read``, retrying while the export share is briefly unavailable."""
    for attempt in range(READ_ATTEMPTS - 1):
        try:
            return read()
        except OSError:
            time.sleep(0.5 * (attempt + 1))
    return read()


def load_readings(paths: Iterable[Path]) -> list[Reading]:
    r"""Load every usable reading from harbour export files.

    Parameters
    ----------
    paths : Iterable[pathlib.Path]
        Export files, in any order.

    Returns
    -------
    list[Reading]
        The readings from every file, leaving out suspect rows.

    Examples
    --------
    >>> import tempfile
    >>> folder = Path(tempfile.mkdtemp())
    >>> header = "station,date,time,level,unit,quality"
    >>> _ = (folder / "a.csv").write_text(f"{header}\nHLX,2026-07-01,12:00,1.5,m,good\\n")
    >>> [reading.level_m for reading in load_readings([folder / "a.csv"])]
    [1.5]
    """
    readings: list[Reading] = []
    for path in paths:
        text = _read_with_retry(lambda: path.read_text("utf-8"))  # noqa: B023 -- called within this iteration
        for row in csv.DictReader(io.StringIO(text)):
            reading = reading_from_row(
                row["station"], row["date"], row["time"], row["level"], row["unit"], row["quality"]
            )
            if reading is not None:
                readings.append(reading)
    return readings


def readings_for_station(readings: Iterable[Reading], station: str) -> list[Reading]:
    """Select one station's readings, in time order.

    Parameters
    ----------
    readings : Iterable[Reading]
        Readings from any stations.
    station : str
        Station code.

    Returns
    -------
    list[Reading]
        That station's readings, earliest first.

    Examples
    --------
    >>> early = Reading("HLX", datetime(2026, 7, 1, 1, tzinfo=UTC), 1.0)
    >>> late = Reading("HLX", datetime(2026, 7, 1, 2, tzinfo=UTC), 2.0)
    >>> other = Reading("YRM", datetime(2026, 7, 1, 1, tzinfo=UTC), 3.0)
    >>> [reading.level_m for reading in readings_for_station([late, other, early], "HLX")]
    [1.0, 2.0]
    """
    selected = (reading for reading in readings if reading.station == station)
    return sorted(selected, key=lambda reading: reading.observed_at)


def readings_between(readings: Sequence[Reading], start: datetime, end: datetime) -> list[Reading]:
    """Select the readings in a half-open time window.

    Parameters
    ----------
    readings : Sequence[Reading]
        Readings to select from.
    start : datetime.datetime
        Start of the window, included.
    end : datetime.datetime
        End of the window, not included.

    Returns
    -------
    list[Reading]
        The readings in the window, in their original order.

    Examples
    --------
    >>> reading = Reading("HLX", datetime(2026, 7, 1, 1, tzinfo=UTC), 1.0)
    >>> readings_between([reading], reading.observed_at, reading.observed_at)
    []
    """
    return [reading for reading in readings if start <= reading.observed_at < end]
