import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = str(ROOT / "examples" / "deploy.sheet")


def run(*args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "runsheet", *args],
        cwd=ROOT, capture_output=True, text=True, input=stdin, timeout=60,
    )


def test_order_prints_one_name_per_line():
    done = run("order", "-", stdin="a\nb: a\n")
    assert done.returncode == 0
    assert done.stdout == "a\nb\n"


def test_example_sheet_order_ends_with_the_smoke_test():
    done = run("order", EXAMPLE)
    assert done.returncode == 0
    lines = done.stdout.splitlines()
    assert lines[0] == "snapshot"
    assert lines[-1] == "smoke test eu"
    assert len(lines) == 7


def test_waves_prints_numbered_lines():
    done = run("waves", "-", stdin="a\nb\nc: a\n")
    assert done.stdout == "1: a b\n2: c\n"


def test_subset_prints_the_needed_steps():
    done = run("subset", "-", "b", stdin="a\nb: a\nc\n")
    assert done.stdout == "a\nb\n"


def test_plan_error_goes_to_stderr():
    done = run("order", "-", stdin="a: b\nb: a\n")
    assert done.returncode == 2
    assert done.stderr.startswith("error: ")
    assert done.stdout == ""
