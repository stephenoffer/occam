"""The nightly job: one collector archive in, one day's rollups out."""

from concurrent.futures import ThreadPoolExecutor, wait

from .archive import load_archive
from .readings import prepare
from .rollup import rollup_station
from .store import write_rollup
from .uplink import push

WORKERS = 8
SOURCE = "nightly"


def _station_job(data_dir, source, station, readings, period):
    write_rollup(data_dir, source, station, rollup_station(readings, period))


def run_nightly(archive, data_dir, date):
    frame = prepare(load_archive(archive))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = [pool.submit(_station_job, data_dir, SOURCE, station, readings, "day")
                for station, readings in frame.groupby("station")]
        wait(jobs)
    push(data_dir, SOURCE, date)
