"""The new site agreement: hours over 10 in a day are overtime too, the weekly 40 counts only the rest.

Every check runs one of the repository's own CLIs on the pay week of 2026-11-02 with three crew members:
  W101  three 12-hour days (36 h)                -> 6 h overtime  (none under the old weekly-only rule)
  W102  four 12-hour days and a 4-hour Friday     -> 12 h overtime (8 daily, then 44 - 40 = 4 weekly; 20 if double counted)
  W103  five 8-hour days and a 6-hour Saturday    -> 6 h overtime  (weekly rule only, unchanged)
Each works at one site and one cost centre, so how premium hours are split between sites can't matter.
The overtime multiplier stays 1.5.
"""

import csv
import json
from decimal import Decimal

import pytest

WEEK = "2026-11-02"
RATES = {"W101": "18.00", "W102": "20.00", "W103": "22.00"}
WHERE = {"W101": ("QSY", "CC-420"), "W102": ("NWK", "CC-410"), "W103": ("HBR", "CC-430")}
SHIFTS = (
    [("W101", f"2026-11-0{d}", "07:00", "19:30", 30) for d in (2, 3, 4)]
    + [("W102", f"2026-11-0{d}", "07:00", "19:30", 30) for d in (2, 3, 4, 5)]
    + [("W102", "2026-11-06", "07:00", "11:00", 0)]
    + [("W103", f"2026-11-0{d}", "07:00", "15:30", 30) for d in (2, 3, 4, 5, 6)]
    + [("W103", "2026-11-07", "07:00", "13:00", 0)]
)
# worker: (total hours, overtime hours, pay for the week)
EXPECTED = {
    "W101": (Decimal(36), Decimal(6), Decimal("702.00")),
    "W102": (Decimal(52), Decimal(12), Decimal("1160.00")),
    "W103": (Decimal(46), Decimal(6), Decimal("1078.00")),
}


def write(path, header, rows):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


@pytest.fixture
def rates(tmp_path):
    names = {"W101": "Dana Okafor", "W102": "Liam Frost", "W103": "Priya Nair"}
    return write(tmp_path / "rates.csv", ["worker_id", "name", "grade", "base_hourly"],
                 [[w, names[w], "skilled", rate] for w, rate in RATES.items()])


@pytest.fixture
def timesheets(tmp_path):
    rows = [[w, day, start, end, unpaid, WHERE[w][0], WHERE[w][1], "approved"] for w, day, start, end, unpaid in SHIFTS]
    return write(tmp_path / "timesheets.csv",
                 ["worker_id", "work_date", "start", "end", "unpaid_break_minutes", "site", "cost_centre", "status"], rows)


@pytest.fixture
def roster(tmp_path):
    rows = [[WHERE[w][0], w, day, start, end, unpaid] for w, day, start, end, unpaid in SHIFTS]
    return write(tmp_path / "roster.csv", ["site", "worker_id", "date", "start", "end", "unpaid_break_minutes"], rows)


def run_json(py, *args):
    done = py("-m", *args, "--json")
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def test_payroll_pays_daily_overtime(py, timesheets, rates):
    out = run_json(py, "payroll", "run", "--timesheets", timesheets, "--rates", rates, "--week", WEEK)
    slips = {slip["worker_id"]: slip for slip in out["payslips"]}
    got = {w: (Decimal(s["regular_hours"]) + Decimal(s["overtime_hours"]), Decimal(s["overtime_hours"]),
               Decimal(s["gross"])) for w, s in slips.items()}
    assert got == EXPECTED


def test_costing_forecast_prices_daily_overtime(py, roster, rates):
    out = run_json(py, "costing", "forecast", "--roster", roster, "--rates", rates)
    sites = {row["site"]: row for row in out["sites"]}
    got = {w: (Decimal(sites[WHERE[w][0]]["hours"]), Decimal(sites[WHERE[w][0]]["premium_hours"]),
               Decimal(sites[WHERE[w][0]]["wages"])) for w in EXPECTED}
    assert got == EXPECTED


def test_accrual_includes_daily_overtime(py, timesheets, rates):
    out = run_json(py, "ledger", "accrue", "--timesheets", timesheets, "--rates", rates, "--month", "2026-11")
    centres = {row["cost_centre"]: row for row in out["cost_centres"]}
    got = {w: (Decimal(centres[WHERE[w][1]]["hours"]), Decimal(centres[WHERE[w][1]]["premium_hours"]),
               Decimal(centres[WHERE[w][1]]["accrued"])) for w in EXPECTED}
    assert got == EXPECTED
    assert Decimal(out["total"]) == sum(pay for _, _, pay in EXPECTED.values())
