"""A partner's historical export in, rollups out."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .archive import load_archive
from .nightly import WORKERS, _station_job
from .readings import prepare
from .uplink import push


def run_backfill(archive, data_dir, partner, period):
    frame = prepare(load_archive(archive))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = [pool.submit(_station_job, data_dir, partner, station, readings, period)
                for station, readings in frame.groupby("station")]
    for job in jobs:
        job.result()
    push(data_dir, partner, Path(archive).stem)
