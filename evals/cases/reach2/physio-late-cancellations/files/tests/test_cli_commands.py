"""The command lines, run in-process the way the desk app calls them."""

import json
from pathlib import Path

import pytest

import appointments.__main__ as appointments_cli
import billing.__main__ as billing_cli
import clinicdb.__main__ as clinicdb_cli
import patients.__main__ as patients_cli
import reports.__main__ as reports_cli
import scheduling.__main__ as scheduling_cli

DEMO_SEED = Path(__file__).resolve().parents[1] / "data" / "demo_seed.json"


@pytest.fixture
def clinic(tmp_path, capsys):
    db = str(tmp_path / "clinic.db")
    assert clinicdb_cli.main(["--db", db, "init"]) == 0
    assert clinicdb_cli.main(["--db", db, "seed", str(DEMO_SEED)]) == 0
    capsys.readouterr()

    def run(cli, *args):
        code = cli.main(["--db", db, *args, "--json"])
        out = capsys.readouterr().out
        assert code == 0, out
        return json.loads(out)
    return run


def test_book_and_history(clinic):
    booked = clinic(appointments_cli, "book", "--patient", "1", "--clinician", "1",
                    "--start", "2026-12-08T10:00", "--at", "2026-12-01T09:00")
    assert booked["status"] == "booked"
    history = clinic(appointments_cli, "history", "1")
    assert [a["id"] for a in history["appointments"]] == [booked["id"]]


def test_cancel_and_free_slots(clinic):
    booked = clinic(appointments_cli, "book", "--patient", "1", "--clinician", "1",
                    "--start", "2026-12-08T09:00", "--at", "2026-12-01T09:00")
    assert "09:00" not in clinic(scheduling_cli, "free", "1", "2026-12-08")["free"]
    cancelled = clinic(appointments_cli, "cancel", str(booked["id"]), "--at", "2026-12-04T09:00")
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_at"] == "2026-12-04T09:00"
    assert "09:00" in clinic(scheduling_cli, "free", "1", "2026-12-08")["free"]


def test_charge_run_and_monthly(clinic):
    booked = clinic(appointments_cli, "book", "--patient", "1", "--clinician", "1",
                    "--start", "2026-12-08T09:00", "--at", "2026-12-01T09:00")
    clinic(appointments_cli, "no-show", str(booked["id"]), "--at", "2026-12-08T09:20")
    run = clinic(billing_cli, "run", "--at", "2026-12-09T02:00")
    assert run["total_pence"] == 3000
    figures = clinic(reports_cli, "monthly", "--month", "2026-12")
    assert figures["totals"]["dna"] == 1
    assert clinic(patients_cli, "deposit", "1", "--on", "2026-12-10")["needs_deposit"] is False


def test_errors_exit_with_code_2(tmp_path, capsys):
    db = str(tmp_path / "clinic.db")
    assert appointments_cli.main(["--db", db, "cancel", "99", "--at", "2026-12-01T09:00"]) == 2
    assert "no appointment 99" in capsys.readouterr().err
