import json
import subprocess
import sys


def settle(tmp_path, returned_on, *extra):
    rental = {"rental_id": "R-55", "customer": "Ada Example", "tool_class": "small", "start_on": "2026-02-23",
              "due_on": "2026-03-02", "deposit_cents": 5000}
    path = tmp_path / "rental.json"
    path.write_text(json.dumps(rental))
    done = subprocess.run([sys.executable, "-m", "toolhire", "settle", "--rental", str(path), "--returned-on", returned_on, *extra],
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_settle_on_time(tmp_path):
    assert settle(tmp_path, "2026-03-02")["released_cents"] == 5000


def test_settle_late(tmp_path):
    assert settle(tmp_path, "2026-03-04")["late_fee_cents"] == 600


def test_settle_with_damage(tmp_path):
    assert settle(tmp_path, "2026-03-02", "--damage-cents", "2000")["captured_cents"] == 2000
