"""Roll one station's readings up into periods."""

import numpy as np

FREQ = {"hour": "h", "day": "D", "month": "MS"}


def _energy(samples):
    if samples.empty:
        return 0.0
    hours = (samples.index - samples.index[0]).total_seconds() / 3600
    return float(np.trapezoid(samples.to_numpy(), hours))


def rollup_station(readings, period):
    """Return total kWh per period for one station's readings, indexed by UTC time."""
    if "kw" in readings:
        return readings["kw"].resample(FREQ[period]).apply(_energy).rename("kwh")
    return readings["kwh"].resample(FREQ[period]).sum().rename("kwh")
