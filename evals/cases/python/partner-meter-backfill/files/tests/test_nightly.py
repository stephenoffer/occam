import csv

from click.testing import CliRunner

from meterhub.__main__ import cli


def run(collector_archive, data_dir):
    result = CliRunner().invoke(
        cli, ["nightly", "--date", "2026-01-05", "--data-dir", str(data_dir), str(collector_archive)])
    assert result.exit_code == 0, result.output
    return result


def test_one_csv_per_station(tmp_path, collector_archive):
    data_dir = tmp_path / "data"
    assert "status=ok" in run(collector_archive, data_dir).output
    with (data_dir / "rollups" / "nightly" / "north-1.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["period"], float(row["kwh"])) for row in rows] == [("2026-01-05T00:00", 4.0), ("2026-01-06T00:00", 4.0)]
    assert (data_dir / "rollups" / "nightly" / "south-2.csv").exists()


def test_rollups_reach_the_spool(tmp_path, collector_archive, spool):
    run(collector_archive, tmp_path / "data")
    assert sorted(path.name for path in (spool / "nightly" / "2026-01-05").iterdir()) == ["north-1.csv", "south-2.csv"]
