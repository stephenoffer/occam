"""Read the archives the collector fleet writes: .npz, or .pkl from collectors not yet upgraded."""

from pathlib import Path

import numpy as np
import pandas as pd


def load_archive(path):
    """Return an archive's readings as a frame with its columns as stored."""
    path = Path(path)
    if path.suffix == ".pkl":
        return pd.read_pickle(path)
    # Collectors store station IDs as Python strings, so these are object arrays.
    with np.load(path, allow_pickle=True) as data:
        return pd.DataFrame({name: data[name] for name in data.files})
