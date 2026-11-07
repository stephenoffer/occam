import json
import subprocess
import sys
from pathlib import Path

from tape_helpers import copy_fixtures

ROOT = Path(__file__).resolve().parents[2]


def backoffice(*args):
    return subprocess.run([sys.executable, "-m", "backoffice", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)


def test_takings_json(tmp_path):
    inbox = copy_fixtures(tmp_path / "inbox")
    done = backoffice("takings", "--inbox", str(inbox), "--date", "2026-10-05", "--json")
    assert done.returncode == 0, done.stderr
    data = json.loads(done.stdout)
    assert data["stores"]["BRH02"]["sales_pence"] == 8295


def test_takings_text_and_postings(tmp_path):
    inbox = copy_fixtures(tmp_path / "inbox")
    text = backoffice("takings", "--inbox", str(inbox), "--date", "2026-10-05").stdout
    assert "BRH02: 3 sales, 82.95" in text and "CHECK" not in text
    csv = backoffice("postings", "--inbox", str(inbox), "--date", "2026-10-05").stdout
    assert csv.startswith("account,store,reference,amount\n") and "4010,BRH02" in csv
