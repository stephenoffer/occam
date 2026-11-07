import json

from costing.__main__ import main
from crew_factories import RATES_HEADER, ROSTER_HEADER, write_csv


def test_forecast_json(tmp_path, capsys):
    roster = write_csv(tmp_path / "plan.csv", ROSTER_HEADER, [
        ["HBR", "W1", "2026-11-02", "07:00", "15:00", "0"],
        ["HBR", "VACANT", "2026-11-03", "07:00", "15:00", "0"],
    ])
    rates = write_csv(tmp_path / "r.csv", RATES_HEADER, [["W1", "Ann", "skilled", "20.00"]])
    assert main(["forecast", "--roster", str(roster), "--rates", str(rates), "--vacant-rate", "20", "--json",
                 "--no-holiday"]) == 0
    out = json.loads(capsys.readouterr().out)
    [site] = out["sites"]
    assert site["hours"] == "16.00"
    assert site["premium_hours"] == "0.00"
    assert site["wages"] == "320.00"
    assert site["oncosts"] == "55.36"
    assert out["total"] == "375.36"


def test_missing_rate_is_reported(tmp_path, capsys):
    roster = write_csv(tmp_path / "plan.csv", ROSTER_HEADER, [["HBR", "W7", "2026-11-02", "07:00", "15:00", "0"]])
    rates = write_csv(tmp_path / "r.csv", RATES_HEADER, [["W1", "Ann", "skilled", "20.00"]])
    assert main(["forecast", "--roster", str(roster), "--rates", str(rates)]) == 2
    assert "W7" in capsys.readouterr().err
