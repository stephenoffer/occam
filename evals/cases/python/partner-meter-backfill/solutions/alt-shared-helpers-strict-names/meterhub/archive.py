"""Read the archives the collector fleet writes: .npz, or .pkl from collectors not yet upgraded."""

from pathlib import Path

import numpy as np
import pandas as pd

PARTNER_COLUMNS = ("station", "ts", "kwh", "kw")


def load_archive(path):
    """Return an archive's readings as a frame with its columns as stored. Only for files we wrote."""
    path = Path(path)
    if path.suffix == ".pkl":
        return pd.read_pickle(path)
    # Collectors store station IDs as Python strings, so these are object arrays.
    with np.load(path, allow_pickle=True) as data:
        return pd.DataFrame({name: data[name] for name in data.files})


def load_partner_archive(path):
    """Partners' files come from outside, so this never unpickles anything in them."""
    with np.load(path, allow_pickle=False) as data:
        return pd.DataFrame({name: data[name] for name in PARTNER_COLUMNS if name in data.files})
