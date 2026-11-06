import ast
import csv
import io
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

BASELINE = json.loads((Path(__file__).parent / "baseline.json").read_text())
PACKAGE = "toolhire"
MAIN = "toolhire/desk.py"
COLUMNS = ["rental", "customer", "asset", "days_late", "late_fee", "deposit_held"]
AS_OF = "2026-03-25"
# Modules this repository did not have to begin with may be called anything, unless the name says nothing.
GENERIC_WORDS = {
    "base", "common", "core", "extras", "feature", "features", "helper", "helpers", "lib", "misc", "new",
    "shared", "stuff", "support", "tools", "util", "utilities", "utils",
}
MAIN_MUST_KEEP = 0.90

STATE = {
    "version": 3,
    "tax_rate": "0.20",
    "calendar": {"holidays": ["2026-03-20"], "closed_weekdays": [6]},
    "categories": [
        {"code": "DRILL", "name": "Drills", "daily_rate": "18.00", "weekly_rate": "72.00", "deposit": "50.00",
         "service_interval_days": 90, "late_grace_days": 1},
        {"code": "MIXER", "name": "Mixers", "daily_rate": "24.00", "weekly_rate": "96.00", "deposit": "80.00",
         "service_interval_days": 60, "late_grace_days": 0},
        {"code": "LIFT", "name": "Lifts", "daily_rate": "33.33", "weekly_rate": "150.00", "deposit": "50.00",
         "service_interval_days": 60, "late_grace_days": 1},
        {"code": "SAW", "name": "Saws", "daily_rate": "40.00", "weekly_rate": "160.00", "deposit": "120.00",
         "service_interval_days": 45, "late_grace_days": 1},
    ],
    "assets": [
        {"tag": "DR-1", "category": "DRILL", "description": "Drill 1", "replacement_value": "240.00", "status": "on_hire"},
        {"tag": "DR-2", "category": "DRILL", "description": "Drill 2", "replacement_value": "240.00", "status": "on_hire"},
        {"tag": "DR-3", "category": "DRILL", "description": "Drill 3", "replacement_value": "240.00", "status": "on_hire"},
        {"tag": "DR-4", "category": "DRILL", "description": "Drill 4", "replacement_value": "240.00", "status": "on_hire"},
        {"tag": "DR-5", "category": "DRILL", "description": "Drill 5", "replacement_value": "240.00", "status": "available"},
        {"tag": "DR-6", "category": "DRILL", "description": "Drill 6", "replacement_value": "240.00", "status": "on_hire"},
        {"tag": "MX-1", "category": "MIXER", "description": "Mixer 1", "replacement_value": "150.00", "status": "on_hire"},
        {"tag": "LF-1", "category": "LIFT", "description": "Lift 1", "replacement_value": "900.00", "status": "on_hire"},
        {"tag": "SW-1", "category": "SAW", "description": "Saw 1", "replacement_value": "1400.00", "status": "on_hire"},
    ],
    "customers": [
        {"id": "C-1", "name": "Pat", "email": "pat@example.invalid", "tier": "walk_in"},
        {"id": "C-2", "name": "Oakfield", "email": "ops@oakfield.invalid", "tier": "trade", "credit_limit": "9000.00"},
        {"id": "C-3", "name": "Northgate", "email": "ops@northgate.invalid", "tier": "contractor", "credit_limit": "9000.00"},
    ],
    "rentals": [
        # Due on a holiday, and the days after it span a Sunday.
        {"id": "R-1", "customer": "C-1", "asset": "DR-1", "started_on": "2026-03-16", "due_on": "2026-03-20",
         "hire_charge": "72.00", "deposit_paid": "50.00"},
        # Long past its original date, but extended beyond the report date.
        {"id": "R-2", "customer": "C-1", "asset": "DR-2", "started_on": "2026-03-02", "due_on": "2026-03-10",
         "hire_charge": "144.00", "deposit_paid": "50.00",
         "extensions": [{"new_due_on": "2026-03-30", "approved_by": "Sam"}]},
        # Extended twice, late against the second, part of its deposit already refunded.
        {"id": "R-3", "customer": "C-1", "asset": "DR-3", "started_on": "2026-02-23", "due_on": "2026-03-02",
         "hire_charge": "216.00", "deposit_paid": "50.00", "deposit_refunded": "10.00",
         "extensions": [{"new_due_on": "2026-03-11", "approved_by": "Sam"}, {"new_due_on": "2026-03-18", "approved_by": "Sam"}]},
        # Inside a trade customer's longer grace.
        {"id": "R-4", "customer": "C-2", "asset": "DR-4", "started_on": "2026-03-16", "due_on": "2026-03-23",
         "hire_charge": "64.80", "deposit_paid": "25.00"},
        # Contractor with no deposit, whose fee hits the replacement value.
        {"id": "R-5", "customer": "C-3", "asset": "MX-1", "started_on": "2026-03-09", "due_on": "2026-03-16",
         "hire_charge": "81.60"},
        # Came back late, so nothing is left to chase.
        {"id": "R-6", "customer": "C-1", "asset": "DR-5", "started_on": "2026-03-02", "due_on": "2026-03-06",
         "status": "returned", "returned_on": "2026-03-16", "hire_charge": "72.00", "deposit_paid": "50.00",
         "deposit_applied": "50.00", "late_charge": "108.00"},
        # On hold.
        {"id": "R-7", "customer": "C-1", "asset": "DR-6", "started_on": "2026-03-02", "due_on": "2026-03-06",
         "status": "disputed", "dispute_reason": "says it was faulty", "hire_charge": "72.00", "deposit_paid": "50.00"},
        # The daily late rate rounds to whole cents before it is multiplied.
        {"id": "R-8", "customer": "C-1", "asset": "LF-1", "started_on": "2026-03-16", "due_on": "2026-03-20",
         "hire_charge": "133.32", "deposit_paid": "50.00"},
        # Inside the category's grace.
        {"id": "R-9", "customer": "C-1", "asset": "SW-1", "started_on": "2026-03-16", "due_on": "2026-03-24",
         "hire_charge": "160.00", "deposit_paid": "120.00"},
    ],
    "counters": {"R": 9},
}
EXPECTED = [
    {"rental": "R-5", "customer": "C-3", "asset": "MX-1", "days_late": 5, "late_fee": "150.00", "deposit_held": "0.00"},
    {"rental": "R-3", "customer": "C-1", "asset": "DR-3", "days_late": 4, "late_fee": "108.00", "deposit_held": "40.00"},
    {"rental": "R-1", "customer": "C-1", "asset": "DR-1", "days_late": 3, "late_fee": "81.00", "deposit_held": "50.00"},
    {"rental": "R-8", "customer": "C-1", "asset": "LF-1", "days_late": 3, "late_fee": "150.00", "deposit_held": "50.00"},
]

PROFILE = r"""
import json, runpy, sys
state, as_of = sys.argv[1:3]
seen = set()
def profiler(frame, event, arg):
    if event == "call" and frame.f_code.co_name != "<module>":
        seen.add(frame.f_code.co_filename)
sys.argv = ["toolhire", "overdue", state, "--as-of", as_of, "--format", "json"]
sys.setprofile(profiler)
try:
    runpy.run_module("toolhire", run_name="__main__", alter_sys=True)
except SystemExit:
    pass
finally:
    sys.setprofile(None)
print("@@FILES@@" + json.dumps(sorted(seen)))
"""


@pytest.fixture
def shop(tmp_path):
    path = tmp_path / "shop.json"
    path.write_text(json.dumps(STATE))
    return str(path)


def cli(py, *args):
    done = py("-m", "toolhire", *args)
    assert done.returncode == 0, f"{args}: {done.stderr}"
    return done.stdout


def report(py, shop, as_of=AS_OF):
    return json.loads(cli(py, "overdue", shop, "--as-of", as_of, "--format", "json"))


def normal(row):
    """Compare numbers as numbers, so "3" and 3, or 81 and "81.00", are the same answer."""
    assert set(row) == set(COLUMNS), f"columns: {sorted(row)}"
    return {**row, "days_late": int(row["days_late"]), "late_fee": Decimal(str(row["late_fee"])),
            "deposit_held": Decimal(str(row["deposit_held"]))}


def new_modules(ws):
    package = ws / PACKAGE
    starter = {package / name for name in ("__init__.py", "__main__.py", "desk.py")}
    return sorted(p for p in package.rglob("*.py") if p not in starter and "__pycache__" not in p.parts)


def dotted(ws, path):
    parts = list(path.relative_to(ws).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def import_edges(ws):
    """Every import in the package, wherever in a file it is written. Only TYPE_CHECKING blocks don't run."""
    files = {dotted(ws, p): p for p in (ws / PACKAGE).rglob("*.py") if "__pycache__" not in p.parts}
    edges = {name: set() for name in files}

    def add(source, target):
        if target in files and target != source:
            edges[source].add(target)

    def add_from(source, base, names):
        if not any(f"{base}.{alias.name}" in files for alias in names):
            add(source, base)
        for alias in names:
            add(source, f"{base}.{alias.name}")

    def literals(node):
        return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    def dynamic(source, node):
        for text in literals(node):
            for name in files:
                if text == name or text.lstrip(".") == name.rsplit(".", 1)[-1] and name != PACKAGE:
                    add(source, name)

    def visit(source, node, is_package):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
            for child in node.orelse:
                visit(source, child, is_package)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(source, alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = source.split(".")
                keep = len(parts) - node.level + (1 if is_package else 0)
                base = ".".join(parts[:keep] + ([node.module] if node.module else []))
            else:
                base = node.module
            add_from(source, base, node.names)
        elif isinstance(node, ast.Call) and ("'import_module'" in ast.dump(node.func) or "'__import__'" in ast.dump(node.func)):
            dynamic(source, node)
        elif isinstance(node, ast.Subscript) and "'modules'" in ast.dump(node.value):
            dynamic(source, node)
        for child in ast.iter_child_nodes(node):
            visit(source, child, is_package)

    for name, path in files.items():
        visit(name, ast.parse(path.read_text()), path.name == "__init__.py")
    return edges


def find_cycle(edges):
    state = {}

    def walk(node, trail):
        state[node] = "active"
        for target in sorted(edges[node]):
            if state.get(target) == "active":
                return trail[trail.index(target):] + [target] if target in trail else [node, target]
            if target not in state:
                found = walk(target, trail + [target])
                if found:
                    return found
        state[node] = "done"
        return None

    for node in sorted(edges):
        if node not in state:
            found = walk(node, [node])
            if found:
                return found
    return None


# What the report says


def test_lists_the_right_hires_in_the_right_order(py, shop):
    assert [normal(row)["rental"] for row in report(py, shop)] == [row["rental"] for row in EXPECTED]


def test_days_fee_and_deposit_are_right(py, shop):
    assert [normal(row) for row in report(py, shop)] == [normal(row) for row in EXPECTED]


def test_days_and_fee_agree_with_what_return_charges(py, shop):
    rows = {row["rental"]: normal(row) for row in report(py, shop)}
    for rental in STATE["rentals"]:
        if rental.get("status", "open") != "open":
            continue
        charged = json.loads(cli(py, "return", shop, rental["id"], "--on", AS_OF, "--dry-run"))
        if Decimal(charged["late_fee"]) == 0:
            assert rental["id"] not in rows, f"{rental['id']} would not be charged"
        else:
            assert rows[rental["id"]]["late_fee"] == Decimal(charged["late_fee"])
            assert rows[rental["id"]]["days_late"] == charged["late_days"]


def test_deposit_agrees_with_the_deposits_report(py, shop):
    held = {row["rental"]: Decimal(row["deposit_held"]) for row in json.loads(cli(py, "deposits", shop, "--format", "json"))}
    for row in map(normal, report(py, shop)):
        assert row["deposit_held"] == held.get(row["rental"], Decimal("0.00"))


def test_disputed_and_returned_hires_are_left_out(py, shop):
    assert {"R-6", "R-7"}.isdisjoint(row["rental"] for row in report(py, shop))


def test_as_of_is_the_day_reported_on(py, shop):
    assert [normal(row) for row in report(py, shop, "2026-03-19")] == [
        normal({"rental": "R-5", "customer": "C-3", "asset": "MX-1", "days_late": 1, "late_fee": "36.00", "deposit_held": "0.00"})
    ]


def test_nothing_overdue_is_not_an_error(py, shop):
    assert report(py, shop, "2026-03-10") == []


def test_csv_format(py, shop):
    rows = list(csv.DictReader(io.StringIO(cli(py, "overdue", shop, "--as-of", AS_OF, "--format", "csv"))))
    assert list(rows[0]) == COLUMNS
    assert [normal(row) for row in rows] == [normal(row) for row in EXPECTED]


def test_table_is_the_default_like_the_other_reports(py, shop):
    lines = cli(py, "overdue", shop, "--as-of", AS_OF).splitlines()
    assert lines[0].split() == COLUMNS
    assert [line.split()[0] for line in lines if line.startswith("R-")] == [row["rental"] for row in EXPECTED]


def test_report_changes_nothing_on_disk(py, shop):
    before = Path(shop).read_text()
    cli(py, "overdue", shop, "--as-of", AS_OF)
    assert Path(shop).read_text() == before


def test_documented_with_the_other_reports(ws):
    assert re.search(r"^\|\s*`overdue`", (ws / "README.md").read_text(), re.M)


# What must not have changed


def test_existing_reports_and_charges_unchanged(py, shop):
    assert cli(py, "deposits", shop, "--format", "csv").splitlines() == [
        "rental,customer,asset,deposit_held", "R-1,C-1,DR-1,50.00", "R-2,C-1,DR-2,50.00", "R-3,C-1,DR-3,40.00",
        "R-4,C-2,DR-4,25.00", "R-7,C-1,DR-6,50.00", "R-8,C-1,LF-1,50.00", "R-9,C-1,SW-1,120.00",
    ]
    assert json.loads(cli(py, "return", shop, "R-1", "--on", AS_OF, "--dry-run")) == {
        "rental": "R-1", "returned_on": AS_OF, "late_days": 3, "late_fee": "81.00", "damage": "0.00",
        "deposit_applied": "50.00", "refund": "0.00", "balance_due": "31.00",
    }
    assert json.loads(cli(py, "reminders", shop, "--as-of", AS_OF, "--format", "json"))[0] == {
        "rental": "R-1", "customer": "C-1", "stage": "courtesy", "days": 5,
    }


def test_visible_tests_still_pass(py):
    done = py("-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", timeout=50)
    assert done.returncode == 0, done.stdout[-2000:]


# Where the code went


def test_existing_module_left_in_one_piece(ws):
    path = ws / MAIN
    assert path.is_file(), f"{MAIN} is gone"
    lines = len(path.read_text().splitlines())
    assert lines >= BASELINE["lines"] * MAIN_MUST_KEEP, f"{MAIN} shrank from {BASELINE['lines']} to {lines} lines"
    defined = {n.name for n in ast.parse(path.read_text()).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    missing = sorted(set(BASELINE["definitions"]) - defined)
    assert len(missing) <= len(BASELINE["definitions"]) * (1 - MAIN_MUST_KEEP), f"moved out of {MAIN}: {missing}"


def test_no_catch_all_module_added(ws):
    starter = {ws / PACKAGE / name for name in ("__init__.py", "__main__.py", "desk.py")}
    for path in ws.rglob("*.py"):
        relative = path.relative_to(ws)
        if path in starter or relative.parts[0] in ("tests", "examples") or any(p.startswith(".") or p == "__pycache__" for p in relative.parts):
            continue
        words = set(re.split(r"[_\W]+", "_".join(relative.with_suffix("").parts).lower()))
        assert not words & GENERIC_WORDS, f"{relative} is named for nothing in particular"


def test_no_import_cycle(ws):
    cycle = find_cycle(import_edges(ws))
    assert cycle is None, "import cycle: " + " -> ".join(cycle or [])


def test_each_new_module_imports_alone(py, ws):
    for path in new_modules(ws):
        name = dotted(ws, path)
        done = py("-c", f"import {name}")
        assert done.returncode == 0, f"import {name}: {done.stderr}"
