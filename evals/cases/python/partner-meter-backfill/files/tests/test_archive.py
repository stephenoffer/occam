from meterhub.archive import load_archive


def test_npz_archive(collector_archive, readings):
    frame = load_archive(collector_archive)
    assert sorted(frame.columns) == ["kwh", "station", "ts"]
    assert list(frame["kwh"]) == list(readings["kwh"])
    assert list(frame["station"]) == list(readings["station"])


def test_pickle_archive_from_older_collectors(tmp_path, readings):
    path = tmp_path / "2026-01-05.pkl"
    readings.to_pickle(path)
    assert list(load_archive(path)["kwh"]) == list(readings["kwh"])
