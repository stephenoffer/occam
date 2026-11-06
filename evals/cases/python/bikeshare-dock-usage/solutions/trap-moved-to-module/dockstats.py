"""Dock usage calculations."""
import csv
from collections import Counter
from datetime import date
from pathlib import Path

REPORT_START = date(2026, 7, 1)
REPORT_END = date(2026, 9, 30)


def read_rows(data, name):
    with open(Path(data) / name, newline="") as handle:
        return list(csv.DictReader(handle))


def days_open(station):
    opened = date.fromisoformat(station["opened_on"])
    return (REPORT_END - max(opened, REPORT_START)).days + 1


def usage(data):
    stations = [s for s in read_rows(data, "stations.csv") if s["status"] != "retired"]
    ids = {s["station"] for s in stations}
    seen, completed = set(), []
    for r in read_rows(data, "rides.csv"):
        if r["ride_id"] in seen:
            continue
        seen.add(r["ride_id"])
        day = date.fromisoformat(r["started_on"])
        if REPORT_START <= day <= REPORT_END and r["status"] == "completed" and r["station"] in ids:
            completed.append(r)
    return stations, completed
