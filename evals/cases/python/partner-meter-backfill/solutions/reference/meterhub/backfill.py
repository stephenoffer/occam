"""A partner's historical export in, rollups out."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .nightly import WORKERS, _station_job
from .readings import prepare
from .uplink import push


def load_partner_archive(path):
    """Read the columns we use. Partners' files come from outside, so nothing here may unpickle."""
    with np.load(path, allow_pickle=False) as data:
        value = "kwh" if "kwh" in data.files else "kw"
        return pd.DataFrame({"station": data["station"], "ts": data["ts"], value: data[value]})


def run_backfill(archive, data_dir, partner, period):
    frame = prepare(load_partner_archive(archive))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = [pool.submit(_station_job, data_dir, partner, station, readings, period)
                for station, readings in frame.groupby("station")]
    for job in jobs:
        job.result()
    push(data_dir, partner, Path(archive).stem)
