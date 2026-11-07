import json
import subprocess
import sys
from pathlib import Path

from helpers import basket, write_basket, write_settings

ROOT = Path(__file__).resolve().parents[1]


def till(data_dir, *args):
    return subprocess.run([sys.executable, "-m", "till", "--data", str(data_dir), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=30)


def test_ring_cashup_close(tmp_path):
    data = tmp_path / "till"
    write_settings(data)
    first = write_basket(tmp_path / "b1.json", basket("2026-11-09T09:00:00", [{"sku": "PNT-1L-WHT"}],
                                                       [{"type": "cash", "pence": 2000}]))
    done = till(data, "ring", str(first))
    assert done.returncode == 0, done.stderr
    assert "CHANGE" in done.stdout and "7.01" in done.stdout

    done = till(data, "cashup", "--date", "2026-11-09", "--counted-cash", "112.99", "--json")
    report = json.loads(done.stdout)
    assert report["sales_total_pence"] == 1299 and report["variance_pence"] == 0

    done = till(data, "close", "--date", "2026-11-09")
    assert done.returncode == 0 and done.stdout.strip().endswith("BRH01-2026-11-09.tape")


def test_refused_sale_exits_2(tmp_path):
    data = tmp_path / "till"
    write_settings(data)
    bad = write_basket(tmp_path / "bad.json", basket("2026-11-09T09:00:00", [{"sku": "NOPE"}], [{"type": "cash", "pence": 1}]))
    done = till(data, "ring", str(bad))
    assert done.returncode == 2 and "not in the catalogue" in done.stderr
