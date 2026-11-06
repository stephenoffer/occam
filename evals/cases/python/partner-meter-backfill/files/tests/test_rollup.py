import pandas as pd

from meterhub.readings import prepare
from meterhub.rollup import rollup_station


def test_prepare_indexes_by_utc_time(readings):
    prepared = prepare(readings)
    assert prepared.index[0] == pd.Timestamp("2026-01-05 08:30", tz="UTC")
    assert prepared.index.is_monotonic_increasing


def test_daily_totals(readings):
    prepared = prepare(readings)
    totals = rollup_station(prepared[prepared["station"] == "north-1"], "day")
    assert totals.tolist() == [4.0, 4.0]
    assert [stamp.strftime("%Y-%m-%d") for stamp in totals.index] == ["2026-01-05", "2026-01-06"]
