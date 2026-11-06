"""Normalise raw readings."""

import pandas as pd


def prepare(frame):
    """Return readings indexed by UTC time, with meter resets counted as zero."""
    frame = frame.copy()
    if "kwh" in frame:
        frame["kwh"][frame["kwh"] < 0] = 0.0
    frame["ts"] = pd.to_datetime(frame["ts"], unit="s", utc=True)
    return frame.set_index("ts").sort_index()
