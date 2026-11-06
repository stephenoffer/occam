import json
from pathlib import Path

import pytest

import original_runsheet
import sheet_driver

HIDDEN = Path(__file__).resolve().parent


@pytest.fixture
def run_cases(py):
    def run(cases, timeout=60):
        done = py(str(HIDDEN / "sheet_driver.py"), input=json.dumps(cases), timeout=timeout)
        assert done.returncode == 0, done.stderr[-2000:]
        return json.loads(done.stdout.splitlines()[-1])
    return run


@pytest.fixture
def same_as_original(run_cases):
    """Every scenario gives what the frozen original gives: value or error, with its details."""
    def check(cases, timeout=60):
        answers = run_cases(cases, timeout)
        assert len(answers) == len(cases)
        for case, got in zip(cases, answers):
            expected = sheet_driver.evaluate(original_runsheet, case)
            assert "crash" not in expected, f"the scenario itself is bad: {case} -> {expected}"
            assert got == expected, f"\n  scenario {case}\n  original {expected}\n  now      {got}"
    return check


@pytest.fixture
def cli(py):
    def run(*args, stdin=None, timeout=60):
        return py("-m", "runsheet", *args, input=stdin, timeout=timeout)
    return run


@pytest.fixture
def original_cli(py):
    def run(*args, stdin=None):
        return py("-m", "original_runsheet", *args, input=stdin, timeout=60,
                  env={"PYTHONPATH": str(HIDDEN)})
    return run
