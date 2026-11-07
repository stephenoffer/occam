#!/usr/bin/env python3
"""Decide "was this planted defect fixed?" by running code, and check what the fix broke.

    oracle_score.py FIXTURE --calibrate            every oracle must fail on the starting code, for its stated reason
    oracle_score.py FIXTURE A.diff B.diff ...      one JSON per diff: oracle results, and original tests that newly fail

FIXTURE is a folder under evals/fixtures with repo/, ANSWERS.json and oracles/. An oracle is a test named test_<defect id with
dashes as underscores>, whose message starts "defect:" when the defect failed it. This runs agent-written code, so each run works
on a scratch copy under sandbox-exec, with an empty HOME and a timeout. Agents may have edited tests, so the original test files
and test configuration go back over the agent's source first.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from pathlib import Path

import grade_workspaces as grade

EVALS = Path(__file__).resolve().parent
FRAME = re.compile(r'^\s*File "([^"]+)", line \d+, in (.+)$')
TRACEBACK = "Traceback (most recent call last):"


def defect_id(test_name: str) -> str:
    return re.sub(r"^test_(.+)_(\w+)$", r"\1-\2", test_name)


def sandboxed(command: list[str], root: Path, cwd: Path, timeout: int) -> tuple[int | None, str]:
    """Run a command confined to root, in a new session so everything it started dies with it. None means it timed out."""
    grade.require_sandbox()
    env = {"PATH": f"{Path(grade.PYTHON).parent}:/usr/bin:/bin", "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"),
           "LANG": "en_US.UTF-8", "PYTHONPATH": str(cwd), "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": str(root)}
    process = subprocess.Popen(["sandbox-exec", "-p", grade.sandbox_profile(root), *command], cwd=cwd, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"
    finally:
        with suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()


@contextmanager
def scratch():
    with tempfile.TemporaryDirectory(prefix="oracle-score-") as name:
        root = Path(os.path.realpath(name))
        for folder in ("home", "tmp"):
            (root / folder).mkdir()
        yield root


def prepare_workspace(fixture: Path, root: Path, diff: Path | None = None) -> tuple[Path, str | None]:
    """A copy of the starting repo with the diff applied, the original tests back, and the oracles beside them."""
    repo, workspace = fixture / "repo", root / "ws"
    shutil.copytree(repo, workspace, symlinks=True)
    if diff is not None:
        shutil.copy(diff, root / "attempt.diff")
        code, output = sandboxed([grade.GIT, "apply", "--whitespace=nowarn", str(root / "attempt.diff")], root, workspace, 120)
        if code != 0:
            return workspace, f"git apply failed: {output.strip()[-2000:]}"
    for folder in ("tests", "oracles"):
        shutil.rmtree(workspace / folder, ignore_errors=True)
    shutil.copytree(repo / "tests", workspace / "tests")
    shutil.copytree(fixture / "oracles", workspace / "oracles")
    if (repo / "pyproject.toml").exists():
        shutil.copy(repo / "pyproject.toml", workspace / "pyproject.toml")
    return workspace, None


def run_pytest(workspace: Path, folder: str, root: Path, timeout: int) -> dict:
    """Run one folder under the sandbox. Returns {"cases": {"module::name": {...}}, "error": text or None}."""
    junit = root / f"{folder}.xml"
    command = [grade.PYTHON, "-m", "pytest", folder, "-q", "-p", "no:cacheprovider", f"--rootdir={workspace}", "--import-mode=importlib",
               "--tb=native", "-o", "junit_logging=all", f"--junitxml={junit}"]
    code, output = sandboxed(command, root, workspace, timeout)
    if code is None or not junit.exists():
        return {"cases": {}, "error": output[-2000:] or "pytest wrote no results"}
    cases = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        problem = next((case.find(tag) for tag in ("failure", "error") if case.find(tag) is not None), None)
        outcome = "failed" if problem is not None else "skipped" if case.find("skipped") is not None else "passed"
        cases[f"{case.get('classname')}::{case.get('name')}"] = {
            "name": case.get("name"), "outcome": outcome, "message": problem.get("message") or "" if outcome == "failed" else "",
            "text": problem.text or "" if outcome == "failed" else "", "log": case.findtext("system-out") or ""}
    return {"cases": cases, "error": None}


def run_on_start(fixture: Path, folder: str, timeout: int) -> dict:
    with scratch() as root:
        workspace, _ = prepare_workspace(fixture, root)
        run = run_pytest(workspace, folder, root, timeout)
    if run["error"]:
        raise SystemExit(f"{folder} did not finish on the starting code: {run['error']}")
    return run


def failure_cause(text: str, workspace: Path, log: str = "") -> tuple[str, str]:
    """The exception type and innermost frame of a failure, preferring the code under test over the tests. A route turns a crash
    into a 500, so the test sees only a failed assert, and the real traceback is then in its captured log."""
    found = []
    for block in (text, log):
        lines = block.rsplit(TRACEBACK, 1)[-1].splitlines() if TRACEBACK in block else []
        frames = [match.groups() for match in map(FRAME.match, lines) if match]
        heads = [line for line in lines if line and not line[0].isspace()]
        exception = re.split(r"[:\s]", heads[0], maxsplit=1)[0].rsplit(".", 1)[-1] if heads else "unknown"
        prefix = f"{workspace}{os.sep}"
        ours = [(path[len(prefix):], name) for path, name in frames if path.startswith(prefix)]
        source = [frame for frame in ours if not frame[0].startswith(("tests/", "oracles/"))]
        if source:
            return exception, ":".join(source[-1])
        found.append((exception, ":".join(ours[-1]) if ours else "unknown"))
    return found[0]


def root_causes(failures: dict[str, tuple[str, str]], workspace: Path) -> list[dict]:
    """Group failing tests, given as name to (traceback, captured log), by exception type and innermost frame in the code under test.
    A failed assert has the test itself as its innermost frame, so one changed line would look like many causes. Those group by test module."""
    groups: dict[tuple[str, str], list[str]] = {}
    for name, (text, log) in sorted(failures.items()):
        exception, frame = failure_cause(text, workspace, log)
        groups.setdefault((exception, frame.split(":")[0] if frame.startswith(("tests/", "oracles/")) else frame), []).append(name)
    return [{"exception": exception, "frame": frame, "tests": tests} for (exception, frame), tests in sorted(groups.items())]


def oracle_results(fixture: Path, run: dict) -> dict[str, dict]:
    """Pass or fail per defect id. An oracle that never ran, say after an import error in the attempt, did not pass."""
    cases = {case["name"]: case for case in run["cases"].values()}
    results = {}
    for name in (name for path in sorted((fixture / "oracles").glob("test_*.py")) for name in re.findall(r"^def (test_\w+)\(", path.read_text(), re.M)):
        case = cases.get(name, {"outcome": "failed", "message": "did not run"})
        passed = None if case["outcome"] == "skipped" else case["outcome"] == "passed"
        results[defect_id(name)] = {"passed": passed, "reason": "skipped" if passed is None else case["message"].split("\n")[0][:300]}
    return results


def score_diff(fixture: Path, diff: Path, baseline: set[str], timeout: int) -> dict:
    record = {"label": diff.stem, "diff": str(diff), "applied": True, "error": None}
    with scratch() as root:
        workspace, problem = prepare_workspace(fixture, root, diff)
        if problem:
            return dict(record, applied=False, error=problem)
        oracles, suite = run_pytest(workspace, "oracles", root, timeout), run_pytest(workspace, "tests", root, timeout)
        record["error"] = " ".join(f"{label} run: {run['error']}" for label, run in (("oracle", oracles), ("suite", suite)) if run["error"]) or None
        if not oracles["error"]:
            record["oracles"] = oracle_results(fixture, oracles)
            record["oracles_passed"] = sum(1 for item in record["oracles"].values() if item["passed"])
        if not suite["error"]:
            failed = {name: case for name, case in suite["cases"].items() if case["outcome"] == "failed"}
            new = {name: (case["text"], case["log"]) for name, case in failed.items() if name not in baseline}
            record["original_tests"] = {"collected": len(suite["cases"]), "failed": len(failed), "newly_failing": len(new)}
            record["root_causes"] = root_causes(new, workspace)
            record["root_cause_count"] = len(record["root_causes"])
    return record


def calibrate(fixture: Path, timeout: int) -> dict:
    """Every oracle must fail on the starting code for its stated reason, and every serious defect must be accounted for."""
    results = oracle_results(fixture, run_on_start(fixture, "oracles", timeout))
    excused = {item["id"]: item["reason"] for item in json.loads((fixture / "oracles" / "NOT_TESTABLE.json").read_text())}
    serious = {item["id"] for item in json.loads((fixture / "ANSWERS.json").read_text()) if item["severity"] in ("critical", "high")}
    return {"oracles": len(results), "not_testable": excused,
            "passes_on_start": sorted(name for name, item in results.items() if item["passed"] is not False),
            "fails_for_another_reason": sorted(name for name, item in results.items() if item["passed"] is False and "defect:" not in item["reason"]),
            "no_oracle": sorted(serious - set(results) - set(excused)), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fixture", help="a folder under evals/fixtures")
    parser.add_argument("diffs", nargs="*", type=Path)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=int, default=600, help="seconds per pytest run")
    args = parser.parse_args()
    fixture, out = EVALS / "fixtures" / args.fixture, args.out or EVALS / "results" / Path(args.fixture).name.removeprefix("blind-") / "oracles"
    out.mkdir(parents=True, exist_ok=True)
    if args.calibrate:
        report = calibrate(fixture, args.timeout)
        (out / "calibration.json").write_text(json.dumps(report, indent=2) + "\n")
        problems = [f"{label}: {name} {report['results'].get(name, {}).get('reason', '')}"
                    for label in ("passes_on_start", "fails_for_another_reason", "no_oracle") for name in report[label]]
        print(f"{report['oracles']} oracles, {len(report['not_testable'])} not testable, {len(problems)} calibration problems", *problems, sep="\n")
        return 1 if problems else 0
    if not args.diffs:
        parser.error("give at least one diff, or --calibrate")
    # Original tests already failing on the starting code don't count against an attempt.
    baseline = {name for name, case in run_on_start(fixture, "tests", args.timeout)["cases"].items() if case["outcome"] == "failed"}
    with ThreadPoolExecutor(3) as pool:
        records = list(pool.map(lambda diff: score_diff(fixture, diff, baseline, args.timeout), args.diffs))
    for record in records:
        (out / f"{record['label']}.json").write_text(json.dumps(record, indent=2) + "\n")
        print(f"{record['label']}: oracles passed {record.get('oracles_passed', 'n/a')}, root causes "
              f"{record.get('root_cause_count', 'n/a')}{', ERROR: ' + record['error'][:200] if record['error'] else ''}")
    return 1 if any(record["error"] for record in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
