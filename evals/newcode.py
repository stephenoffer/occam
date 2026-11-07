#!/usr/bin/env python3
"""Does code written with the plugin cost less to change later? The new-code test in evals/PREREGISTRATION.md.

    newcode.py pilot SPEC           billed: one no-skill build and its change, to prove the pipeline
    newcode.py run SPEC             billed: 3 builds per arm from an empty repository, with the frozen plugin
    newcode.py change SPEC          billed: one fresh no-skill agent makes the change on each finished build
    newcode.py score SPEC           hidden tests on each build and each change, and lines the change touched
    newcode.py report               per-spec differences and the signed-rank test

SPEC is a folder under evals/fixtures holding prompt.md, change.md, hidden/ and hidden_change/. The second agent never has the plugin, so it isn't the variable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import audit_comparison as harness
import grade_workspaces as grade
import oracle_score as oracles
import study

EVALS = Path(__file__).resolve().parent
RESULTS = EVALS / "results"
CAP_USD = 75.0
RESERVE_USD = 12.0  # one spec's builds or changes, with room to spare
FRONT_MATTER = """---
tags: [newcode]
max_turns: 80
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

"""
TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.py$|conftest\.py$)")


def counted(path: str) -> bool:
    """Product code only: tests may grow freely, and generated files aren't anyone's work."""
    return not TEST_PATH.search(path) and not path.endswith((".pyc", ".lock")) and "__pycache__/" not in path and not path.startswith(".claude/")


def lines_changed(numstat: str) -> int:
    total = 0
    for line in numstat.splitlines():
        added, deleted, path = line.split("\t", 2)
        if added != "-" and counted(path):
            total += int(added) + int(deleted)
    return total


def change_cost(lines: int, passed: bool, worst_passing: int) -> int:
    """A change that fails its hidden tests counts as twice the spec's largest passing change."""
    return lines if passed else 2 * worst_passing


def spec_gap(costs: dict[str, list[int]]) -> float | None:
    """No skill's median minus the plugin's, as a share of no skill's. Positive means plugin code took less changing."""
    if not costs.get("with") or not costs.get("without"):
        return None
    base = statistics.median(costs["without"])
    return (base - statistics.median(costs["with"])) / base if base else None


def _stage(out: Path, files: Path | None, prompt: str, plugin: Path | None) -> None:
    (out / ".claude-plugin").mkdir(parents=True)
    (out / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "occam", "description": "Evaluation stage."}) + "\n")
    for part in ("skills", "hooks", "agents") if plugin else ():
        shutil.copytree(plugin / part, out / part, ignore=shutil.ignore_patterns("__pycache__"))
    case = out / "evals" / harness.CASE
    (case / "graders").mkdir(parents=True)
    if files:
        shutil.copytree(files, case / "files", ignore=shutil.ignore_patterns(".git", ".claude", "__pycache__", ".pytest_cache"))
    else:
        (case / "files").mkdir()
        (case / "files" / ".gitkeep").write_text("")
    (case / "prompt.md").write_text(FRONT_MATTER + prompt)
    (case / "case.yaml").write_text(harness.CASE_YAML)
    (case / "place-files.sh").write_text(harness.PLACE_FILES)
    (case / "graders" / "01-final-message.md").write_text(harness.GRADERS["02-final-message.md"])


def _eval(label: str, files: Path | None, prompt: str, plugin: Path | None, runs: int) -> dict:
    out = RESULTS / label
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    with tempfile.TemporaryDirectory(prefix="newcode-stage-") as folder:
        stage = Path(folder) / "stage"
        _stage(stage, files, prompt, plugin)
        out.mkdir(parents=True)
        command = ["caffeinate", "-ims", "claude", "plugin", "eval", str(stage), "--scaffold", "--runs", str(runs), "--ablation", "with-without" if plugin else "none", "--keep-temp", "--no-publish",
                   "--trust-plugin", "--model", "claude-sonnet-5-5", "-j", "2", "--max-cost-usd", str(RESERVE_USD), "--threshold", "0", "--output-dir", str(out), "--allow-tools", "Bash", "Write", "Edit"]
        with open(out / "eval.log", "w") as log:
            status = subprocess.run(command, cwd=stage, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "CLAUDE_CODE_PROMPT_CACHE_TTL": "5m"}).returncode
    document = json.loads((out / "aggregate-result.json").read_text())
    with open(RESULTS / "ledger.jsonl", "a") as ledger:
        ledger.write(json.dumps({"step": label, "variant": "plugin" if plugin else "empty", "cost_usd": document["costUsd"], "partial": document["partial"], "exit": status,
                                 "claude": document["claudeVersion"], "model": "claude-sonnet-5-5", "plugin_sha256": harness._plugin_hash(plugin) if plugin else None}) + "\n")
    return document


def _guard() -> None:
    if not (study.may_start(study.spent("study-newcode"), CAP_USD, RESERVE_USD) and study.may_start(study.spent(), study.TOTAL_CAP_USD, RESERVE_USD)):
        raise SystemExit(f"stopping: ${study.spent('study-newcode'):.2f} on this test and ${study.spent():.2f} in all. Report the rest as not run.")


def _builds(label: str) -> list[tuple[str, int, Path]]:
    document = json.loads((RESULTS / label / "aggregate-result.json").read_text())
    return [(arm, index, grade.open_kept(Path(run["tracePath"]))) for arm, runs in document["cases"][0]["arms"].items() for index, run in enumerate(runs)]


def _hidden(workspace: Path, tests: Path, timeout: int = 300) -> dict:
    """Run a spec's hidden tests on a copy of a workspace, sandboxed because agents wrote this code."""
    with oracles.scratch() as root:
        copy = root / "ws"
        shutil.copytree(workspace, copy, ignore=shutil.ignore_patterns(".git", ".claude", "__pycache__", ".pytest_cache"))
        shutil.copytree(tests, copy / "hidden_tests")
        shim = copy / "hidden_tests" / "conftest.py"  # hidden tests find the code through this variable, and the sandbox sets its own environment
        shim.write_text(f"import os\nos.environ['NEWCODE_REPO'] = {str(copy)!r}\n" + (shim.read_text() if shim.exists() else ""))
        run = oracles.run_pytest(copy, "hidden_tests", root, timeout)
    outcomes = [case["outcome"] for case in run["cases"].values()]
    return {"error": run["error"], "total": len(outcomes), "passed": outcomes.count("passed")}


def changes(spec: str, label: str | None = None) -> None:
    label = label or f"study-{spec}-build"
    fixture = EVALS / "fixtures" / spec
    prompt = (fixture / "change.md").read_text()

    def one(build: tuple[str, int, Path]) -> None:
        arm, index, workspace = build
        _eval(f"{label}-change-{arm}-{index}", workspace, prompt, None, 1)

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(one, _builds(label)))


def score(spec: str, label: str | None = None) -> list[dict]:
    label = label or f"study-{spec}-build"
    fixture = EVALS / "fixtures" / spec
    rows = []
    for arm, index, workspace in _builds(label):
        row = {"arm": arm, "run": index, "build": _hidden(workspace, fixture / "hidden")}
        changed = RESULTS / f"{label}-change-{arm}-{index}" / "aggregate-result.json"
        if changed.exists():
            run = json.loads(changed.read_text())["cases"][0]["arms"]
            run = next(iter(run.values()))[0]
            second = grade.open_kept(Path(run["tracePath"]))
            subprocess.run([grade.GIT, "add", "-A", "-N", "."], cwd=second, capture_output=True)
            numstat = subprocess.run([grade.GIT, "diff", "--numstat", "HEAD"], cwd=second, capture_output=True, text=True).stdout
            hidden = _hidden(second, fixture / "hidden_change")
            row["change"] = {"lines": lines_changed(numstat), "hidden": hidden, "passed": not hidden["error"] and hidden["total"] > 0 and hidden["passed"] == hidden["total"], "cost_usd": run.get("costUsd")}
        rows.append(row)
    passing = [row["change"]["lines"] for row in rows if row.get("change", {}).get("passed")]
    worst = max(passing) if passing else 0
    for row in rows:
        if "change" in row:
            row["cost"] = change_cost(row["change"]["lines"], row["change"]["passed"], worst)
    (RESULTS / label / "scores.json").write_text(json.dumps(rows, indent=2) + "\n")
    return rows


def report() -> dict:
    per_spec = {}
    for path in sorted(RESULTS.glob("study-newcode2-*-build/scores.json")):
        rows = json.loads(path.read_text())
        costs = {arm: [row["cost"] for row in rows if row["arm"] == arm and "cost" in row] for arm in ("with", "without")}
        accept = {arm: [row["build"]["passed"] / row["build"]["total"] for row in rows if row["arm"] == arm and row["build"]["total"]] for arm in ("with", "without")}
        per_spec[path.parent.name] = {"costs": costs, "gap": spec_gap(costs), "acceptance": {arm: statistics.mean(found) if found else None for arm, found in accept.items()}}
    gaps = [row["gap"] for row in per_spec.values() if row["gap"] is not None]
    summary = {"specs": per_spec, "n": len(gaps), "spent_usd": round(study.spent("study-newcode"), 2)}
    if gaps:
        summary.update(estimate=study.hodges_lehmann(gaps), p=study.signed_rank_p(gaps))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("pilot", "run", "change", "score", "report"))
    parser.add_argument("spec", nargs="?")
    args = parser.parse_args()
    fixture = EVALS / "fixtures" / str(args.spec)
    if args.action == "pilot":
        _guard()
        label = f"study-{args.spec}-pilot"
        _eval(label, None, (fixture / "prompt.md").read_text(), None, 1)
        changes(args.spec, label)
        print(json.dumps(score(args.spec, label), indent=1))
    elif args.action == "run":
        _guard()
        if not study.FROZEN.exists():
            raise SystemExit("run `study.py freeze` first")
        _eval(f"study-{args.spec}-build", None, (fixture / "prompt.md").read_text(), study.FROZEN, 3)
    elif args.action == "change":
        _guard()
        changes(args.spec)
    elif args.action == "score":
        print(json.dumps(score(args.spec), indent=1))
    else:
        print(json.dumps(report(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
