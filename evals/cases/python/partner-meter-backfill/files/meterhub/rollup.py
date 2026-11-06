"""Roll one station's readings up into periods."""

FREQ = {"hour": "H", "day": "D", "month": "M"}


def rollup_station(readings, period):
    """Return total kWh per period for one station's readings, indexed by UTC time."""
    return readings["kwh"].resample(FREQ[period]).sum().rename("kwh")
