"""The batch jobs: one archive in, rollups out."""

from concurrent.futures import ThreadPoolExecutor

from .archive import load_archive, load_partner_archive
from .readings import prepare
from .rollup import rollup_station
from .store import write_rollup
from .uplink import push

WORKERS = 8
SOURCE = "nightly"


def _roll_up_all(frame, data_dir, source, period):
    def job(item):
        station, readings = item
        write_rollup(data_dir, source, station, rollup_station(readings, period))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(job, frame.groupby("station")))


def run_nightly(archive, data_dir, date):
    _roll_up_all(prepare(load_archive(archive)), data_dir, SOURCE, "day")
    push(data_dir, SOURCE, date)


def run_partner(archive, data_dir, partner, period):
    _roll_up_all(prepare(load_partner_archive(archive)), data_dir, partner, period)
    push(data_dir, partner, "backfill")
