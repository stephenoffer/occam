import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def spool(tmp_path, monkeypatch):
    path = tmp_path / "spool"
    monkeypatch.setenv("METERHUB_SPOOL", str(path))
    return path


@pytest.fixture
def readings():
    """Two stations over two days, as the collectors report them."""
    stamps = ["2026-01-05 08:30", "2026-01-05 17:45", "2026-01-06 09:10", "2026-01-05 12:00"]
    return pd.DataFrame({
        "station": np.array(["north-1", "north-1", "north-1", "south-2"], dtype=object),
        "ts": [int(pd.Timestamp(stamp, tz="UTC").timestamp()) for stamp in stamps],
        "kwh": [1.5, 2.5, 4.0, 3.0],
    })


@pytest.fixture
def collector_archive(tmp_path, readings):
    path = tmp_path / "2026-01-05.npz"
    np.savez(path, station=readings["station"].to_numpy(dtype=object), ts=readings["ts"].to_numpy(),
             kwh=readings["kwh"].to_numpy())
    return path
