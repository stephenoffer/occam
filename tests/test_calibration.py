"""Prove each case's hidden checks can detect what they claim to.

For every case: the untouched starter fails, solutions/reference passes, and each
solutions/trap-* (a plausible wrong fix) fails, on at least the tests named in its
EXPECT_FAIL file. A solution is an overlay of changed files; it may also contain
__post__.sh (run in the workspace), __final_message__.txt and __trace__.jsonl.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import grade_workspaces as grade

EVALS = Path(__file__).resolve().parents[1] / "evals"
CASES = sorted(p for suite in ("smoke", "holdout", "regression", "python", "hard") for p in (EVALS / "cases" / suite).glob("*")
               if (p / "hidden").is_dir())
SPECIAL = {"__post__.sh", "__final_message__.txt", "__trace__.jsonl", "EXPECT_FAIL"}


def case_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


IMPORT_NAMES = {"pyyaml": "yaml", "scikit-learn": "sklearn", "pillow": "PIL", "python-dateutil": "dateutil", "beautifulsoup4": "bs4"}


def skip_without_its_packages(case_dir: Path) -> None:
    """A case that pins third-party packages can't be calibrated without them, and an import error would make every check fail for
    the wrong reason. CI installs them with `--group cases` where the Python version allows, and says so when it skips."""
    lock = case_dir / "files" / "requirements.lock"
    if not lock.exists():
        return
    names = [line.split("==")[0].strip().lower() for line in lock.read_text().splitlines() if "==" in line and not line.lstrip().startswith("#")]
    modules = [IMPORT_NAMES.get(name, name.replace("-", "_")) for name in names]
    probe = "import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in sys.argv[1:]) else 1)"
    if subprocess.run([grade.PYTHON, "-c", probe, *modules], capture_output=True, timeout=60).returncode:
        pytest.skip(f"{case_id(case_dir)} needs {', '.join(names)}, which {grade.PYTHON} doesn't have: `pip install --group cases`, on Python 3.11 or later")


def apply_solution(solution: Path, workspace: Path) -> tuple[str, Path | None]:
    for source in solution.rglob("*"):
        relative = source.relative_to(solution)
        if source.is_file() and relative.name not in SPECIAL:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
    post = solution / "__post__.sh"
    if post.exists():
        subprocess.run(["bash", str(post)], cwd=workspace, check=True, capture_output=True,
                       env={"PATH": f"{Path(grade.GIT).parent}:/usr/bin:/bin"})
    message = solution / "__final_message__.txt"
    trace = solution / "__trace__.jsonl"
    return (message.read_text() if message.exists() else "", trace if trace.exists() else None)


@pytest.fixture(params=CASES, ids=case_id)
def case(request) -> Path:
    skip_without_its_packages(request.param)
    return request.param


def test_starter_fails(case, tmp_path):
    workspace = tmp_path / "ws"
    grade.build_starter(case, workspace)
    result = grade.run_hidden(case, workspace)
    assert result["collected"] > 0, result["output"]
    assert not result["passed"], "hidden checks pass on the untouched starter, so they detect nothing"


def test_reference_passes(case, tmp_path):
    workspace = tmp_path / "ws"
    grade.build_starter(case, workspace)
    message, trace = apply_solution(case / "solutions" / "reference", workspace)
    result = grade.run_hidden(case, workspace, message, trace)
    assert result["passed"], f"failed: {result['failed']}\n{result['output']}"


@pytest.mark.parametrize("case_dir", [c for c in CASES if (c / "hidden" / "visible_state.json").exists()],
                         ids=case_id)
def test_visible_suite_is_in_the_state_the_case_assumes(case_dir, tmp_path):
    """Catches a false premise, such as a "pre-existing failure" that does not actually fail."""
    skip_without_its_packages(case_dir)
    workspace = tmp_path / "ws"
    grade.build_starter(case_dir, workspace)
    report = tmp_path / "visible.xml"
    subprocess.run([grade.PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
                   cwd=workspace, capture_output=True, timeout=120)
    cases = list(ET.parse(report).getroot().iter("testcase"))
    assert cases, "the visible suite collected nothing"
    state = {"failed": sum(c.find("failure") is not None or c.find("error") is not None for c in cases),
             "skipped": sum(c.find("skipped") is not None for c in cases)}
    assert state == json.loads((case_dir / "hidden" / "visible_state.json").read_text())


def traps() -> list[Path]:
    return [t for c in CASES for t in sorted((c / "solutions").glob("trap-*"))]


@pytest.mark.parametrize("trap", traps(), ids=lambda t: f"{t.parents[2].name}/{t.parents[1].name}/{t.name}")
def test_trap_fails_for_the_intended_reason(trap, tmp_path):
    case_dir = trap.parents[1]
    skip_without_its_packages(case_dir)
    workspace = tmp_path / "ws"
    grade.build_starter(case_dir, workspace)
    message, trace = apply_solution(trap, workspace)
    result = grade.run_hidden(case_dir, workspace, message, trace)
    assert not result["passed"], "the wrong solution passes, so the checks miss this defect"
    expected = (trap / "EXPECT_FAIL").read_text().split()
    missing = [name for name in expected if not any(name in failed for failed in result["failed"])]
    assert not missing, f"expected these to fail: {missing}; actually failed: {result['failed']}"
