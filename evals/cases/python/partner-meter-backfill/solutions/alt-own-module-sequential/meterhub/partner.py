"""Partner backfill, independent of the collector pipeline: its formats and trust differ."""

import shlex
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

TOOL = Path(__file__).resolve().parents[1] / "tools" / "push-rollups"
BUCKET = {"hour": "%Y-%m-%dT%H:00", "day": "%Y-%m-%d", "month": "%Y-%m"}


def read_export(path):
    with np.load(path) as data:
        kind = "kw" if "kw" in data.files else "kwh"
        frame = pd.DataFrame({"station": data["station"], "ts": data["ts"], kind: data[kind]})
    return frame, kind


def integrate(samples):
    ordered = samples.sort_values("ts")
    hours = ordered["ts"].to_numpy(dtype=float) / 3600
    power = ordered["kw"].to_numpy()
    return float(np.sum(np.diff(hours) * (power[1:] + power[:-1]) / 2))


def backfill_archive(archive, data_dir, partner, period):
    frame, kind = read_export(archive)
    frame["bucket"] = pd.to_datetime(frame["ts"], unit="s", utc=True).dt.strftime(BUCKET[period])
    out_dir = Path(data_dir) / "rollups" / partner
    out_dir.mkdir(parents=True, exist_ok=True)
    for station, readings in frame.groupby("station"):
        if kind == "kw":
            energy = {bucket: integrate(group) for bucket, group in readings.groupby("bucket")}
        else:
            energy = readings[readings["kwh"] > 0].groupby("bucket")["kwh"].sum().to_dict()
        rows = pd.DataFrame({"period": list(energy), "kwh": list(energy.values())})
        rows.to_csv(out_dir / f"{station}.csv", index=False)
    command = shlex.join([str(TOOL), "--source", partner, "--label", Path(archive).stem, str(out_dir)])
    log = shlex.quote(str(Path(data_dir) / "push.log"))
    subprocess.run(["bash", "-c", f"set -o pipefail; {command} 2>&1 | tee -a {log}"], check=True)
