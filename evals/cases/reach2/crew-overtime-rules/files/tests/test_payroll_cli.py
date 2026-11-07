import json

from crew_factories import RATES_HEADER, TIMESHEET_HEADER, write_csv
from payroll.__main__ import main


def inputs(tmp_path, rows):
    timesheets = write_csv(tmp_path / "t.csv", TIMESHEET_HEADER, rows)
    rates = write_csv(tmp_path / "r.csv", RATES_HEADER, [["W1", "Ann Bell", "skilled", "20.00"],
                                                          ["W2", "Bo Diaz", "operative", "18.00"]])
    return ["run", "--timesheets", str(timesheets), "--rates", str(rates), "--week", "2026-11-02", "--json"]


def test_json_payslips(tmp_path, capsys):
    rows = [["W1", f"2026-11-0{d}", "07:00", "15:30", "30", "QSY", "CC-420", "approved"] for d in range(2, 7)]
    rows.append(["W1", "2026-11-07", "08:00", "12:00", "0", "QSY", "CC-420", "approved"])
    rows.append(["W2", "2026-11-02", "08:00", "12:00", "0", "QSY", "CC-420", "approved"])
    assert main(inputs(tmp_path, rows)) == 0
    out = json.loads(capsys.readouterr().out)
    slips = {slip["worker_id"]: slip for slip in out["payslips"]}
    assert slips["W1"]["regular_hours"] == "40.00"
    assert slips["W1"]["overtime_hours"] == "4.00"
    assert slips["W1"]["gross"] == "920.00"
    assert slips["W2"]["gross"] == "72.00"
    assert out["total_gross"] == "992.00"


def test_unapproved_shifts_are_noted_not_paid(tmp_path, capsys):
    rows = [["W1", "2026-11-02", "07:00", "15:00", "0", "QSY", "CC-420", "approved"],
            ["W1", "2026-11-03", "07:00", "15:00", "0", "QSY", "CC-420", "submitted"]]
    assert main(inputs(tmp_path, rows)) == 0
    [slip] = json.loads(capsys.readouterr().out)["payslips"]
    assert slip["regular_hours"] == "8.00"
    assert slip["notes"]


def test_problems_stop_the_run(tmp_path, capsys):
    rows = [["W1", "2026-11-02", "07:00", "12:00", "0", "QSY", "CC-420", "approved"],
            ["W1", "2026-11-02", "11:00", "15:00", "0", "QSY", "CC-420", "approved"]]
    assert main(inputs(tmp_path, rows)) == 1
    assert "overlap" in capsys.readouterr().err


def test_week_must_be_a_monday(tmp_path, capsys):
    args = inputs(tmp_path, [])
    args[args.index("2026-11-02")] = "2026-11-03"
    assert main(args) == 2
