"""Acceptance for `python3 -m meterhub backfill`, judged only by what it writes, delivers and exits with."""

import csv
import math
import pickle
from datetime import datetime, timezone

import numpy as np
import pytest

PARTNER = "northgrid"


def epoch(stamp):
    return int(datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp())


class Planted:
    """Unpickles to a call that leaves a file behind, so running the loader on it can be observed."""

    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (open, (str(self.path), "w"))


def write_archive(path, rows, value="kwh", **overrides):
    """Write rows of (station, stamp, value) in the documented format, including the partner's free-text notes."""
    width = max(len(row[0]) for row in rows)
    arrays = {
        "station": np.array([row[0] for row in rows], dtype=f"U{width}"),
        "ts": np.array([epoch(row[1]) for row in rows], dtype=np.int64),
        value: np.array([row[2] for row in rows], dtype=np.float64),
        "note": np.array(["estimated" if index % 2 else None for index in range(len(rows))], dtype=object),
    }
    arrays.update(overrides)
    with path.open("wb") as handle:
        np.savez(handle, **arrays)
    return path


READINGS = [
    ("S1", "2026-01-30T10:15:00", 1.0),
    ("S1", "2026-01-30T10:45:00", 2.0),
    ("S1", "2026-01-30T11:20:00", 4.0),
    ("S1", "2026-02-02T03:05:00", 8.0),
    ("S2", "2026-01-31T23:50:00", 16.0),
    ("S2", "2026-02-01T00:10:00", 32.0),
]
EXPECTED = {
    "hour": (13, {"S1": {"2026-01-30T10": 3.0, "2026-01-30T11": 4.0, "2026-02-02T03": 8.0},
                  "S2": {"2026-01-31T23": 16.0, "2026-02-01T00": 32.0}}),
    "day": (10, {"S1": {"2026-01-30": 7.0, "2026-02-02": 8.0}, "S2": {"2026-01-31": 16.0, "2026-02-01": 32.0}}),
    "month": (7, {"S1": {"2026-01": 7.0, "2026-02": 8.0}, "S2": {"2026-01": 16.0, "2026-02": 32.0}}),
}


@pytest.fixture
def backfill(py, tmp_path):
    data, spool = tmp_path / "data", tmp_path / "spool"
    data.mkdir()
    spool.mkdir()

    def run(archive, partner=PARTNER, period="day", spool_dir=None):
        return py("-m", "meterhub", "backfill", "--partner", partner, "--period", period,
                  "--data-dir", str(data), str(archive), env={"METERHUB_SPOOL": str(spool_dir or spool)})

    run.data, run.spool = data, spool
    return run


def totals(data, station, width, source=PARTNER):
    """Energy per bucket, keyed by the leading part of the label. Empty buckets may or may not be written."""
    path = data / "rollups" / source / f"{station}.csv"
    assert path.is_file(), f"no rollup at {path}"
    found = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            value = float(row["kwh"] or 0)
            if value and not math.isnan(value):
                key = row["period"].replace(" ", "T")[:width]
                found[key] = found.get(key, 0.0) + value
    return found


@pytest.mark.parametrize("period", ["hour", "day", "month"])
def test_period_totals(backfill, tmp_path, period):
    done = backfill(write_archive(tmp_path / "export.npz", READINGS), period=period)
    assert done.returncode == 0, done.stderr
    width, expected = EXPECTED[period]
    for station, buckets in expected.items():
        assert totals(backfill.data, station, width) == pytest.approx(buckets)


def test_meter_reset_counts_as_zero(backfill, tmp_path):
    rows = [("S1", "2026-03-04T08:15:00", 1.5), ("S1", "2026-03-04T09:15:00", -40.0), ("S1", "2026-03-04T10:15:00", 2.5)]
    done = backfill(write_archive(tmp_path / "export.npz", rows))
    assert done.returncode == 0, done.stderr
    assert totals(backfill.data, "S1", 10) == pytest.approx({"2026-03-04": 4.0})


def test_power_archive_is_integrated_per_period(backfill, tmp_path):
    rows = [
        ("P1", "2026-02-03T01:00:00", 0.0), ("P1", "2026-02-03T02:00:00", 2.0), ("P1", "2026-02-03T05:00:00", 2.0),
        ("P1", "2026-02-04T10:00:00", 4.0), ("P1", "2026-02-04T10:30:00", 0.0),
        ("P2", "2026-02-03T00:30:00", 3.0), ("P2", "2026-02-03T02:30:00", 3.0),
    ]
    done = backfill(write_archive(tmp_path / "export.npz", rows, value="kw"))
    assert done.returncode == 0, done.stderr
    assert totals(backfill.data, "P1", 10) == pytest.approx({"2026-02-03": 7.0, "2026-02-04": 1.0})
    assert totals(backfill.data, "P2", 10) == pytest.approx({"2026-02-03": 6.0})


def test_rollups_reach_the_spool(backfill, tmp_path):
    done = backfill(write_archive(tmp_path / "export.npz", READINGS))
    assert done.returncode == 0, done.stderr
    delivered = {path.name for path in backfill.spool.rglob("*.csv")}
    assert delivered >= {"S1.csv", "S2.csv"}


@pytest.mark.parametrize("column", ["note", "kwh"])
def test_pickled_column_does_not_run(backfill, tmp_path, column):
    marker = tmp_path / "planted"
    path = write_archive(tmp_path / "export.npz", READINGS,
                         **{column: np.array([Planted(marker)] * len(READINGS), dtype=object)})
    done = backfill(path)
    assert not marker.exists(), "a pickle inside the partner's file ran"
    if column != "note":
        assert done.returncode != 0, "a column we need could not be used, so this must not report success"
    elif done.returncode == 0:
        assert list(backfill.data.rglob("S1.csv")), "reported success without loading anything"


@pytest.mark.parametrize("suffix", ["npz", "pkl"])
def test_pickle_file_does_not_run(backfill, tmp_path, suffix):
    marker = tmp_path / "planted"
    path = tmp_path / f"export.{suffix}"
    path.write_bytes(pickle.dumps(Planted(marker)))
    done = backfill(path)
    assert not marker.exists(), "the partner's file ran as a pickle"
    assert done.returncode != 0


def files_named(roots, name):
    return [path for root in roots for path in root.rglob("*") if path.name == name]


@pytest.mark.parametrize("partner, filename, marker", [
    ("$(touch planted-a)", "export.npz", "planted-a"),
    (";touch planted-b;", "export.npz", "planted-b"),
    ("'$(touch planted-c)'", "export.npz", "planted-c"),
    (PARTNER, "export$(touch planted-d).npz", "planted-d"),
], ids=["partner-substitution", "partner-separator", "partner-quote", "filename-substitution"])
def test_names_never_run_as_commands(backfill, ws, tmp_path, partner, filename, marker):
    done = backfill(write_archive(tmp_path / filename, READINGS), partner=partner)
    assert not files_named([ws, tmp_path], marker), "a name from the partner ran as a shell command"
    if done.returncode == 0:
        assert list(backfill.data.rglob("S1.csv")), "reported success without loading anything"


def test_failed_delivery_is_visible(backfill, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    done = backfill(write_archive(tmp_path / "export.npz", READINGS), spool_dir=blocker / "spool")
    assert done.returncode != 0, "delivery failed and the run reported success"


def test_failed_station_is_visible(backfill, tmp_path):
    rows = [("S1", "2026-01-30T10:15:00", 1.0), ("S" * 300, "2026-01-30T10:15:00", 2.0), ("T1", "2026-01-30T10:15:00", 4.0)]
    done = backfill(write_archive(tmp_path / "export.npz", rows))
    assert done.returncode != 0, "a station could not be written and the run reported success"


@pytest.mark.parametrize("kind", ["garbage", "no-values"])
def test_unusable_archive_is_visible(backfill, tmp_path, kind):
    path = tmp_path / "export.npz"
    if kind == "garbage":
        path.write_bytes(b"this is not an archive\n")
    else:
        with path.open("wb") as handle:
            np.savez(handle, station=np.array(["S1"], dtype="U2"), ts=np.array([epoch("2026-01-30T10:15:00")]))
    assert backfill(path).returncode != 0


@pytest.mark.parametrize("suffix", ["npz", "pkl"])
def test_nightly_still_reads_collector_archives(py, tmp_path, suffix):
    import pandas as pd

    frame = pd.DataFrame({
        "station": np.array(["north-1", "north-1", "south-2"], dtype=object),
        "ts": [epoch("2026-01-05T08:30:00"), epoch("2026-01-06T09:10:00"), epoch("2026-01-05T12:00:00")],
        "kwh": [1.5, 4.0, 3.0],
    })
    path = tmp_path / f"2026-01-05.{suffix}"
    if suffix == "pkl":
        frame.to_pickle(path)
    else:
        np.savez(path, station=frame["station"].to_numpy(dtype=object), ts=frame["ts"].to_numpy(), kwh=frame["kwh"].to_numpy())
    data, spool = tmp_path / "data", tmp_path / "spool"
    done = py("-m", "meterhub", "nightly", "--date", "2026-01-05", "--data-dir", str(data), str(path),
              env={"METERHUB_SPOOL": str(spool)})
    assert done.returncode == 0, done.stderr
    assert totals(data, "north-1", 10, source="nightly") == pytest.approx({"2026-01-05": 1.5, "2026-01-06": 4.0})
    assert {item.name for item in spool.rglob("*.csv")} >= {"north-1.csv", "south-2.csv"}
