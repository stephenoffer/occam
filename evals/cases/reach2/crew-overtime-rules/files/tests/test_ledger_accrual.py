import json

from crew_factories import RATES_HEADER, TIMESHEET_HEADER, write_csv
from ledger.__main__ import main


def run(tmp_path, capsys, rows, month="2026-11", extra=()):
    timesheets = write_csv(tmp_path / "t.csv", TIMESHEET_HEADER, rows)
    rates = write_csv(tmp_path / "r.csv", RATES_HEADER, [["W1", "Ann Bell", "skilled", "20.00"],
                                                          ["W2", "Bo Diaz", "operative", "18.50"]])
    code = main(["accrue", "--timesheets", str(timesheets), "--rates", str(rates), "--month", month, "--json",
                 *extra])
    out = capsys.readouterr()
    assert code == 0, out.err
    return {row["cost_centre"]: row for row in json.loads(out.out)["cost_centres"]}, json.loads(out.out)


def row(worker, day, start, end, unpaid=0, centre="CC-420", status="approved"):
    return [worker, day, start, end, str(unpaid), "QSY", centre, status]


def test_accrues_base_and_premium_by_cost_centre(tmp_path, capsys):
    rows = [row("W1", f"2026-11-0{d}", "07:00", "15:30", 30) for d in range(2, 7)]
    rows.append(row("W1", "2026-11-07", "08:00", "14:00", centre="CC-410"))
    centres, out = run(tmp_path, capsys, rows)
    assert centres["CC-420"]["premium_hours"] == "0.00"
    assert centres["CC-420"]["accrued"] == "800.00"
    assert centres["CC-410"]["premium_hours"] == "6.00"
    assert centres["CC-410"]["accrued"] == "180.00"
    assert out["total"] == "980.00"


def test_long_days_under_forty_are_accrued_at_base(tmp_path, capsys):
    rows = [row("W2", f"2026-11-0{d}", "07:00", "19:30", 30) for d in range(2, 5)]
    centres, _ = run(tmp_path, capsys, rows)
    assert centres["CC-420"]["hours"] == "36.00"
    assert centres["CC-420"]["premium_hours"] == "0.00"
    assert centres["CC-420"]["accrued"] == "666.00"


def test_only_approved_shifts_in_the_months_weeks(tmp_path, capsys):
    rows = [row("W1", "2026-11-02", "07:00", "15:00"), row("W1", "2026-11-03", "07:00", "15:00", status="draft"),
            row("W1", "2026-10-30", "07:00", "15:00"), row("W1", "2026-12-07", "07:00", "15:00")]
    centres, out = run(tmp_path, capsys, rows)
    assert centres["CC-420"]["hours"] == "8.00"
    assert out["weeks"][0] == "2026-11-02"


def test_quarter_hour_rounding_matches_payroll(tmp_path, capsys):
    rows = [row("W2", "2026-11-02", "07:00", "13:10")]
    centres, _ = run(tmp_path, capsys, rows)
    assert centres["CC-420"]["hours"] == "6.25"
    assert centres["CC-420"]["accrued"] == "115.63"


def test_writes_the_finance_journal(tmp_path, capsys):
    rows = [row("W1", "2026-11-02", "07:00", "15:00")]
    journal = tmp_path / "journal.csv"
    run(tmp_path, capsys, rows, extra=("--journal-out", str(journal)))
    lines = journal.read_text().splitlines()
    assert lines[1].startswith("5100,CC-420,160.00,")
    assert lines[2].startswith("2210,,,160.00,")
