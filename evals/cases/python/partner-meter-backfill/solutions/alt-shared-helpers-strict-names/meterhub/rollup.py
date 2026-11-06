"""Roll one station's readings up into periods."""

FREQ = {"hour": "h", "day": "D", "month": "ME"}


def _trapezoid(samples):
    """kWh from kW samples indexed by time."""
    total = 0.0
    points = list(samples.items())
    for (start, left), (end, right) in zip(points, points[1:]):
        total += (left + right) / 2 * (end - start).total_seconds() / 3600
    return total


def rollup_station(readings, period):
    """Return total kWh per period for one station's readings, indexed by UTC time."""
    if "kwh" in readings:
        return readings["kwh"].resample(FREQ[period]).sum().rename("kwh")
    return readings["kw"].resample(FREQ[period]).apply(_trapezoid).rename("kwh")
