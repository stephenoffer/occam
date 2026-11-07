import json
import shutil
import subprocess
import sys

PAYLOADS = [({"id": 7, "total_cents": 1200, "status": "paid", "discount_cents": 150}, "Order 7: $12.00 (paid, $1.50 off)"),
            ({"id": 8, "total_cents": 999, "status": "shipped", "discount_cents": 0}, "Order 8: $9.99 (shipped)")]


def render_in(folder, payload):
    code = "import json, sys; from cli.show_order import render; print(render(json.loads(sys.argv[1])))"
    done = subprocess.run([sys.executable, "-c", code, json.dumps(payload)], cwd=folder, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-800:]
    return done.stdout.strip()


def test_the_discount_shows_as_delivered(ws):
    for payload, shown in PAYLOADS:
        assert render_in(ws, payload) == shown


def test_it_survives_regenerating_the_client(ws, tmp_path):
    """CI regenerates the client from the schema, so a change that lives only in the generated file is lost."""
    copy = tmp_path / "copy"
    shutil.copytree(ws, copy, ignore=shutil.ignore_patterns(".git"))
    done = subprocess.run([sys.executable, "tools/gen_client.py"], cwd=copy, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-800:]
    for payload, shown in PAYLOADS:
        assert render_in(copy, payload) == shown


def test_the_committed_client_matches_the_generator(ws, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(ws, copy, ignore=shutil.ignore_patterns(".git"))
    subprocess.run([sys.executable, "tools/gen_client.py"], cwd=copy, capture_output=True, text=True, timeout=60, check=True)
    assert (copy / "clients" / "orders_generated.py").read_text() == (ws / "clients" / "orders_generated.py").read_text()
