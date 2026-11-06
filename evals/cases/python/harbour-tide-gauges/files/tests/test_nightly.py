from datetime import date
from pathlib import Path

from tidekit.nightly import main, month_bounds

DATA = Path(__file__).resolve().parents[1] / "data"


def test_month_bounds_handle_a_leap_february():
    assert month_bounds(date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))


def test_job_lists_every_station(capsys):
    status = main([
        "--export", str(DATA / "harbour-export.csv"),
        "--offsets", str(DATA / "datum_offsets.json"),
        "--day", "2026-07-02",
    ])  # fmt: skip
    assert status == 0
    printed = capsys.readouterr().out
    assert [line.split()[0] for line in printed.splitlines()] == ["HLX", "SYD", "YRM"]
