import ast
import json
import os
import re
import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).parent
BASELINE = json.loads((HERE / "baseline.json").read_text())
GOLDEN = json.loads((HERE / "golden.json").read_text())
PACKAGE = "grainbank"
OLD = "grainbank.settlement"
STARTER = {"__init__.py", "taskapp.py", "worker.py", "settlement.py"}
NESTED_TIMEOUT = 20
BOARD = {"prices": {"corn": "4.3725", "soybeans": "10.1150", "wheat": "5.6200"}}
OLD_TASKS = [
    "grainbank.settlement.nightly_close",
    "grainbank.settlement.refresh_board_prices",
    "grainbank.settlement.reverse_ticket",
    "grainbank.settlement.send_statement",
    "settlement.reconcile",
]
TICKETS = [
    {"id": "T-1", "member": "M-1", "commodity": "corn", "gross_lb": 60117, "tare_lb": 27233, "moisture": "17.3",
     "test_weight": "55.1", "foreign_material": "1.37", "weighed_on": "2026-11-04", "location": "east"},
    {"id": "T-2", "member": "M-2", "commodity": "soybeans", "gross_lb": 58211, "tare_lb": 28000, "moisture": "13.0",
     "test_weight": "57", "foreign_material": "0.5", "weighed_on": "2026-11-04", "location": "river"},
    {"id": "T-3", "member": "M-1", "commodity": "rye", "gross_lb": 58211, "tare_lb": 28000, "moisture": "13.0",
     "test_weight": "57", "foreign_material": "0.5", "weighed_on": "2026-11-04"},
]


@pytest.fixture
def world(tmp_path):
    """Local stand-ins for the feed and the alert hook, so that no check reaches for a network."""
    feed = tmp_path / "board.json"
    feed.write_text(json.dumps(BOARD))
    hook = tmp_path / "alerts"
    hook.write_text("")
    return {"GRAINBANK_FEED_URL": f"file://{feed}", "GRAINBANK_ALERT_URL": f"file://{hook}"}


def run_worker(py, world, *args):
    return py("-m", "grainbank.worker", *args, env=world)


def worker_json(py, world, *args):
    done = run_worker(py, world, *args)
    assert done.returncode == 0, f"{args}: {done.stderr[-1500:]}"
    return json.loads(done.stdout)


def old_module_file(ws):
    as_file = ws / PACKAGE / "settlement.py"
    return as_file if as_file.is_file() else ws / PACKAGE / "settlement" / "__init__.py"


def package_modules(ws):
    return sorted(p for p in (ws / PACKAGE).rglob("*.py") if "__pycache__" not in p.parts)


def new_modules(ws):
    old = old_module_file(ws)
    package = ws / PACKAGE
    return [p for p in package_modules(ws) if p != old and not (p.parent == package and p.name in STARTER)]


def dotted(ws, path):
    parts = list(path.relative_to(ws).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def top_level_definitions(path):
    return {n.name for n in ast.parse(path.read_text()).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def import_edges(ws):
    """Every import in the package, wherever in a file it is written. Only TYPE_CHECKING blocks don't run."""
    files = {dotted(ws, p): p for p in package_modules(ws)}
    edges = {name: set() for name in files}

    def add(source, target):
        if target in files and target != source:
            edges[source].add(target)

    def add_from(source, base, names):
        if not any(f"{base}.{alias.name}" in files for alias in names):
            add(source, base)
        for alias in names:
            add(source, f"{base}.{alias.name}")

    def dynamic(source, node):
        for literal in ast.walk(node):
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                for name in files:
                    short = name.rsplit(".", 1)[-1]
                    if name != PACKAGE and (literal.value == name or literal.value.lstrip(".") == short):
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
                return trail[trail.index(target):] + [target]
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


def nested_env():
    """The workspace first, as usual, and this directory for the plugin that nested test runs load."""
    return {"PYTHONPATH": os.pathsep.join([os.environ["EVAL_WORKSPACE"], str(HERE)])}


def run_copied_tests(py, tmp_path, sources):
    """Run test files exactly as the evaluator holds them, whatever has happened to the repository's copies."""
    target = tmp_path / "copied"
    target.mkdir()
    for source, name in sources:
        shutil.copy(source, target / name)
    return py("-m", "pytest", str(target), "-q", "-p", "no:cacheprovider", "-p", "no_real_sleep", f"--rootdir={target}", "--tb=short",
              timeout=NESTED_TIMEOUT, env=nested_env())


# It was actually moved


def test_old_module_really_was_broken_up(ws):
    definitions = set(BASELINE["definitions"])
    still_there = top_level_definitions(old_module_file(ws)) & definitions
    assert len(still_there) <= len(definitions) / 2, f"{len(still_there)} of {len(definitions)} definitions never left"
    holding = [p for p in new_modules(ws) if top_level_definitions(p) & definitions]
    assert len(holding) >= 2, f"moved code should end up in several modules, found {[p.name for p in holding]}"


def test_each_class_is_defined_once(ws):
    classes = BASELINE["classes"]
    homes = {name: [] for name in classes}
    for path in package_modules(ws):
        for name in top_level_definitions(path) & set(classes):
            homes[name].append(path.name)
    assert {name: where for name, where in homes.items() if len(where) != 1} == {}


# Each new module stands alone


def test_each_new_module_imports_alone(py, ws):
    added = new_modules(ws)
    assert added, "no new modules"
    for path in added:
        name = dotted(ws, path)
        done = py("-c", f"import {name}")
        assert done.returncode == 0, f"import {name} in a fresh process: {done.stderr[-800:]}"


def test_no_import_cycle(ws):
    cycle = find_cycle(import_edges(ws))
    assert cycle is None, "import cycle: " + " -> ".join(cycle or [])


# Old imports


def test_every_old_name_is_still_at_the_old_path(py):
    names = BASELINE["public"] + ["_quantize_bushels", "_Cursor", "_PRICE_CACHE", "time", "urlopen", "app"]
    script = f"import {OLD} as m, json; print(json.dumps([n for n in {names!r} if not hasattr(m, n)]))"
    done = py("-c", script)
    assert done.returncode == 0, done.stderr[-800:]
    assert json.loads(done.stdout) == []


def test_other_teams_code_still_runs(py, tmp_path):
    (tmp_path / "ledger.json").write_text("[]")
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import coop_portal as p, feedmill_sync as f; from decimal import Decimal as D;"
        "assert p.season_banner() == 'Current season: 2026-fall', p.season_banner();"
        "assert p.roll_over('2027-spring') == 'Current season: 2027-spring', 'season banner is stale';"
        "assert 'Season: Spring 2027' in p.preview_statement('M-1', sys.argv[2]);"
        "assert p.display_bushels(D('1.005')) == '1.01 bu';"
        "print('ok')"
    )
    done = py("-c", script, str(HERE / "downstream"), str(tmp_path / "ledger.json"))
    assert done.returncode == 0, done.stderr[-1500:]


def test_season_rollover_stays_visible_at_the_old_path(py):
    done = py(str(HERE / "season_probe.py"))
    assert done.returncode == 0, done.stderr[-1500:]


# Patch targets


def test_original_tests_pass_unchanged(py, tmp_path):
    done = run_copied_tests(py, tmp_path, [(HERE / "original_tests" / "test_settlement.py.txt", "test_settlement.py")])
    assert done.returncode == 0, done.stdout[-3000:]


def test_other_teams_tests_pass_unchanged(py, tmp_path):
    done = run_copied_tests(py, tmp_path, [
        (HERE / "downstream" / "test_feedmill_sync.py.txt", "test_feedmill_sync.py"),
        (HERE / "downstream" / "feedmill_sync.py", "feedmill_sync.py"),
    ])
    assert done.returncode == 0, done.stdout[-3000:]


def test_old_patch_targets_reach_the_moved_code_and_undo(py):
    done = py(str(HERE / "patch_probe.py"))
    assert done.returncode == 0, done.stderr[-1500:]


def test_visible_tests_not_weakened(ws):
    original = {}
    for node in ast.walk(ast.parse((HERE / "original_tests" / "test_settlement.py.txt").read_text())):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            original[node.name] = sum(isinstance(n, ast.Assert) for n in ast.walk(node)) + ast.dump(node).count("assert_")
    found = {}
    for path in (ws / "tests").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                marks = " ".join(ast.dump(d) for d in node.decorator_list)
                body = ast.dump(node)
                disabled = re.search(r"'(skip|skipif|xfail)'", marks) or re.search(r"'(skip|xfail)'", body)
                count = sum(isinstance(n, ast.Assert) for n in ast.walk(node)) + body.count("assert_")
                found[node.name] = (count, bool(disabled))
    problems = {}
    for name, wanted in original.items():
        if name not in found:
            problems[name] = "gone"
        elif found[name][1]:
            problems[name] = "skipped"
        elif found[name][0] < wanted:
            problems[name] = f"{found[name][0]} assertions, was {wanted}"
    assert problems == {}


def test_repository_test_suite_passes(py):
    done = py("-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "-p", "no_real_sleep", timeout=NESTED_TIMEOUT, env=nested_env())
    assert done.returncode == 0, done.stdout[-2000:]


# Task names


def test_old_task_names_are_all_still_registered(py, world):
    done = run_worker(py, world, "--list")
    assert done.returncode == 0, done.stderr[-800:]
    assert set(OLD_TASKS) <= set(done.stdout.split()), done.stdout


def test_saved_broker_messages_still_run(py, world, tmp_path):
    ledger = tmp_path / "ledger.json"
    assert worker_json(py, world, "run", "grainbank.settlement.nightly_close", "--args",
                       json.dumps([write_tickets(tmp_path), str(ledger), str(tmp_path)]))["result"]["settled"] == ["T-1", "T-2"]
    messages = tmp_path / "messages.json"
    messages.write_text(json.dumps([
        {"task": "settlement.reconcile", "args": ["M-2", str(ledger), "0.00"]},
        {"task": "grainbank.settlement.send_statement", "args": ["M-2", str(ledger), str(tmp_path)]},
        {"task": "grainbank.settlement.reverse_ticket", "args": ["T-2", "wrong member", str(ledger)]},
        {"task": "grainbank.settlement.refresh_board_prices", "args": []},
    ]))
    done = worker_json(py, world, "drain", str(messages))
    assert [item["task"] for item in done] == [
        "settlement.reconcile", "grainbank.settlement.send_statement", "grainbank.settlement.reverse_ticket",
        "grainbank.settlement.refresh_board_prices",
    ]
    assert done[0]["result"]["matches"] is False
    assert done[1]["result"] == "2026-fall-M-2.txt"
    assert done[2]["result"]["member"] == "M-2"
    assert done[3]["result"] == {"corn": "4.3725", "soybeans": "10.1150", "wheat": "5.6200"}


def write_tickets(tmp_path):
    path = tmp_path / "tickets.json"
    path.write_text(json.dumps(TICKETS))
    return str(path)


def test_nightly_close_still_chains_to_its_statements(py, world, tmp_path):
    ledger, statements = tmp_path / "ledger.json", tmp_path / "statements"
    statements.mkdir()
    out = worker_json(py, world, "run", "grainbank.settlement.nightly_close", "--args",
                      json.dumps([write_tickets(tmp_path), str(ledger), str(statements)]))
    assert out["result"] == GOLDEN["close"]
    assert out["chained"] == [
        {"task": "grainbank.settlement.send_statement", "result": "2026-fall-M-1.txt"},
        {"task": "grainbank.settlement.send_statement", "result": "2026-fall-M-2.txt"},
    ], "the chained task has to keep going by its registered name"
    text = re.sub(r"Generated: \S+", "Generated: X", (statements / "2026-fall-M-1.txt").read_text())
    assert text == GOLDEN["close_statement"]


# Stored checkpoints


@pytest.mark.parametrize("fixture,season", [("checkpoint_2025_fall.pkl", "2025-fall"), ("checkpoint_2024_fall.pkl", "2026-fall")])
def test_stored_checkpoints_still_load_and_finish(py, world, tmp_path, fixture, season):
    copy = tmp_path / fixture
    shutil.copy(HERE / fixture, copy)
    ledger = tmp_path / "ledger.json"
    out = worker_json(py, world, "resume", str(copy), "--ledger", str(ledger))
    assert out == {"season": season, "settled": GOLDEN["resume"][fixture]["settled"]}
    entries = json.loads(ledger.read_text())
    assert [entry["amount"] for entry in entries] == GOLDEN["resume"][fixture]["amounts"]


def test_stored_checkpoint_is_the_class_at_the_old_path(py):
    script = (
        "import pickle, sys, grainbank.settlement as s;"
        "c = pickle.load(open(sys.argv[1], 'rb'));"
        "assert isinstance(c, s.SettlementCheckpoint);"
        "assert isinstance(c.cursor, s._Cursor);"
        "assert isinstance(c.tickets[0], s.Ticket);"
        "assert isinstance(c.results[0], s.PricedTicket);"
        "assert c.results[0].grade is s.Grade.NO1;"
        "assert c.cursor.last_ticket == 'T-701'; print('ok')"
    )
    done = py("-c", script, str(HERE / "checkpoint_2025_fall.pkl"))
    assert done.returncode == 0, done.stderr[-1500:]


# Behavior


def test_what_it_computes_has_not_changed(py):
    done = py(str(HERE / "golden_probe.py"))
    assert done.returncode == 0, done.stderr[-1500:]
    got = json.loads(done.stdout)
    changed = {key: (got.get(key), GOLDEN["probe"][key]) for key in GOLDEN["probe"] if got.get(key) != GOLDEN["probe"][key]}
    assert changed == {}, "behavior changed"
