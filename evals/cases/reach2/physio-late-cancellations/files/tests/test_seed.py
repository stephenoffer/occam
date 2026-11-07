import json
from pathlib import Path

from clinicdb.connect import open_db
from clinicdb.seed import load_seed_file

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo_seed.json"


def test_demo_seed_loads():
    db = open_db(":memory:")
    counts = load_seed_file(db, DEMO)
    assert counts == {"clinics": 3, "clinicians": 4, "sessions": 10, "patients": 4}


def test_demo_seed_sessions_are_well_formed():
    data = json.loads(DEMO.read_text())
    for clinician in data["clinicians"]:
        for session in clinician["sessions"]:
            assert 0 <= session["weekday"] <= 6
            assert session["starts"] < session["ends"]
