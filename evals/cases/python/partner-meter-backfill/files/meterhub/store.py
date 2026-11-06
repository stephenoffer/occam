"""Where rollups live."""

from pathlib import Path


def rollup_path(data_dir, source, station):
    return Path(data_dir) / "rollups" / source / f"{station}.csv"


def write_rollup(data_dir, source, station, totals):
    target = rollup_path(data_dir, source, station)
    target.parent.mkdir(parents=True, exist_ok=True)
    out = totals.to_frame("kwh")
    out.index = out.index.strftime("%Y-%m-%dT%H:%M")
    out.index.name = "period"
    out.to_csv(target)
    return target
