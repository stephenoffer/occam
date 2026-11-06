"""The prompt's size, latency and correctness targets, through Workbook and the CLI."""

import json
import subprocess
import time
from pathlib import Path

import pytest

SCENARIOS = str(Path(__file__).parent / "workbook_scenarios.py")
CHILD_TIMEOUT = 30
CLI_LIMIT_SECONDS = 20  # twice the 10 seconds the prompt asks for


@pytest.fixture
def scenario(py):
    def run(name, argument=None, timeout=CHILD_TIMEOUT):
        args = [SCENARIOS, name] + ([argument] if argument else [])
        try:
            done = py(*args, timeout=timeout)
        except subprocess.TimeoutExpired:
            pytest.fail(f"{name}({argument}) did not finish in {timeout}s")
        assert done.returncode == 0, f"{name}({argument}) crashed:\n{done.stderr[-1500:]}"
        return json.loads(done.stdout.strip().splitlines()[-1])
    return run


@pytest.mark.parametrize("order", ["forward", "reverse", "shuffled"])
def test_long_chain(scenario, order):
    result = scenario("long_chain", order)
    assert result["seen"] == result["expected"]


@pytest.mark.parametrize("order", ["forward", "reverse"])
def test_layers_of_shared_subtotals(scenario, order):
    result = scenario("shared_subtotals", order)
    assert result["seen"] == result["expected"]


def test_what_if_edit_and_read_rounds(scenario):
    result = scenario("what_if", "shuffled", timeout=60)
    assert "wrong" not in result, result.get("wrong")
    assert "over_budget" not in result, result.get("over_budget")


def test_forward_references_pick_up_later_cells(scenario):
    result = scenario("forward_references")
    assert result["seen"] == result["expected"]


def test_replacing_a_formula_rewires_dependencies(scenario):
    result = scenario("rewiring")
    assert result["seen"] == result["expected"]


def test_random_edits_match_independent_evaluation(scenario):
    result = scenario("random_edits")
    assert result == {"ok": True}, result


def test_long_cycle_is_reported_and_recovers(scenario):
    result = scenario("long_cycle")
    assert result["reported"] is True
    assert result["unrelated"] == 4
    assert result["after"] == result["expected_after"]


def test_short_cycles_are_reported_and_recover(scenario):
    result = scenario("short_cycles")
    assert result == {"first": 2.0, "introduced": True, "recovered": 6.0, "self_loop": True, "self_after": 2.0}


def test_arithmetic_errors_keep_raising_until_fixed(scenario):
    result = scenario("errors")
    assert result["raised"] == [True, True, True]
    assert result["seen"] == result["expected"]


def test_cli_on_a_model_of_the_stated_size(py, scenario, tmp_path):
    model = tmp_path / "model.json"
    assert scenario("write_model", str(model))["cells"] >= 55_000
    started = time.perf_counter()
    try:
        done = py("-m", "pricemodel", str(model), timeout=CLI_LIMIT_SECONDS)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the CLI did not finish in {CLI_LIMIT_SECONDS}s")
    assert done.returncode == 0, done.stderr[-1500:]
    assert time.perf_counter() - started < CLI_LIMIT_SECONDS

    lines = done.stdout.splitlines()
    assert lines == sorted(lines, key=lambda line: line.split(" = ")[0])
    values = dict(line.split(" = ") for line in lines)
    assert float(values["chain.29999"]) == 30000
    assert float(values["rollup.total"]) == 25000
    assert float(values["rung.63.b"]) == 2.0 ** 63


def test_cli_reports_a_long_cycle_with_status_2(py, scenario, tmp_path):
    model = tmp_path / "cycle.json"
    scenario("write_cycle_model", str(model))
    try:
        done = py("-m", "pricemodel", str(model), timeout=CLI_LIMIT_SECONDS)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the CLI did not finish in {CLI_LIMIT_SECONDS}s")
    assert done.returncode == 2, done.stderr[-1500:]
