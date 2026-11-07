#!/usr/bin/env python3
"""Does occam-audit help? The same audit-and-repair task, with and without the plugin, scored against a key no run can see.

    audit_comparison.py stage DIR [--fixture NAME]                       build the stage and stop. Free.
    audit_comparison.py run LABEL --max-cost-usd 10 [--fixture NAME]     billed: real model runs. Logged in results/ledger.jsonl
    audit_comparison.py score LABEL [--fixture NAME]                     score a finished run again. Free.

Scored for each run: defects located by AUDIT.md (the answer key's file and line), decoys wrongly reported, whether the repository's
tests still pass after the agent's changes (run on a copy, in a sandbox), lines changed, cost and time. "Located" means pointing
at the right place, not understanding it. Report the counts, not a significance claim: three runs per arm supports description only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import grade_workspaces as grade
import score_audit
import stage as staging

EVALS = Path(__file__).resolve().parent
FIXTURE = EVALS / "fixtures" / "blind-audit"
LARGE_LIMITS = (("max_turns: 80", "max_turns: 150"), ("timeout_seconds: 1500", "timeout_seconds: 2700"))
KEEP_LINE_NUMBERS = "\nKeep the line numbers in AUDIT.md as they were in the original code, even after you change things.\n"
RESULTS = EVALS / "results"
CASE = "audit-blind"
PROMPT = """---
tags: [audit]
max_turns: 80
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

This service was mostly written by an AI assistant and we're about to put real customers on it. Audit it and fix what you safely can.

First write AUDIT.md at the repository root: every problem you find, one per line or bullet, each with its location as `path:line` in the code as it stands now, what goes wrong, and how sure you are. Then fix what you safely can, without changing public behavior or the data model. Nobody is available to answer questions during this run, so add a section to AUDIT.md listing any decision you need from a person, and what you recommend. Don't commit.
"""
CASE_YAML = """schema_version: "1.1"
name: audit-blind
tags: [audit]
expected_outcome: |
  AUDIT.md lists the real problems in this service with file and line, and safe fixes are applied without breaking its tests.
context:
  scaffold_script: place-files.sh
"""
GRADERS = {
    "01-skill-fired.md": """---
type: tool_used
tool: Skill
input_match: '"(occam:)?occam-audit"'
arm: with-only
---
""",
    "02-final-message.md": """---
type: regex
pattern: "\\\\S"
target: last_message
arm: both
---
""",
}
PLACE_FILES = """#!/usr/bin/env bash
set -eu
here="$(dirname "$0")"
cp -R "$here/files/." .
git init -q .
git -c user.name=maintainer -c user.email=maintainer@example.invalid add -A
git -c user.name=maintainer -c user.email=maintainer@example.invalid commit -qm "Initial import"
"""


def _use_fixture(folder: Path) -> None:
    global FIXTURE
    FIXTURE = folder
    score_audit.FIXTURE = folder


def build_stage(out: Path, plugin: Path | None = staging.PLUGIN, prompt: str | None = None) -> None:
    """A plugin root holding everything a user installs, plus the case. The answer key stays behind. plugin=None stages no plugin."""
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    (out / ".claude-plugin").mkdir(parents=True)
    (out / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "occam", "description": "Evaluation stage."}) + "\n")
    ignored = shutil.ignore_patterns("__pycache__", ".pytest_cache")
    for part in ("skills", "hooks", "agents") if plugin else ():
        shutil.copytree(plugin / part, out / part, ignore=ignored)
    case = out / "evals" / CASE
    case.mkdir(parents=True)
    shutil.copytree(FIXTURE / "repo", case / "files", ignore=ignored)
    if prompt is None:
        prompt = PROMPT
        if FIXTURE.name != "blind-audit":
            for old, new in LARGE_LIMITS:
                prompt = prompt.replace(old, new)
            prompt += KEEP_LINE_NUMBERS
    (case / "prompt.md").write_text(prompt)
    (case / "case.yaml").write_text(CASE_YAML)
    (case / "place-files.sh").write_text(PLACE_FILES)
    (case / "graders").mkdir()
    for name, content in GRADERS.items():
        (case / "graders" / name).write_text(content)
    staging.add_environment_note(case / "prompt.md")
    leaked = [p for p in out.rglob("*") if p.name in ("ANSWERS.json", "DECOYS.json", "ITEMS.json", "SPEC.md") or p.name == "oracles"]
    if leaked:
        raise SystemExit(f"the answer key reached the stage: {leaked}")


def _tests_pass(workspace: Path) -> bool | None:
    """Run the repository's own tests on a copy, sandboxed, because this executes agent-written code."""
    grade.require_sandbox()
    with tempfile.TemporaryDirectory(prefix="audit-grade-") as folder:
        copy = Path(folder) / "workspace"
        shutil.copytree(workspace, copy, symlinks=True, ignore=shutil.ignore_patterns(".git", ".claude"))
        environment = {"PATH": "/usr/bin:/bin", "HOME": folder, "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": folder}
        try:
            done = subprocess.run(["sandbox-exec", "-p", grade.sandbox_profile(Path(folder)), grade.PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                  cwd=copy, env=environment, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return False
        return done.returncode == 0


def score(label: str) -> list[dict]:
    out = RESULTS / label
    document = json.loads((out / "aggregate-result.json").read_text())
    rows = []
    for case in document["cases"]:
        for arm, runs in case["arms"].items():
            for index, run in enumerate(runs):
                rows.append(_score_run(out, arm, index, run))
    (out / "scores.json").write_text(json.dumps(rows, indent=2))
    return rows


def _score_run(out: Path, arm: str, index: int, run: dict) -> dict:
    row = {"arm": arm, "run": index, "cost_usd": run.get("costUsd"), "seconds": run.get("durationSeconds") or run.get("durationMs"), "error": run.get("error")}
    kept = out / "reports" / f"{arm}-{index}"
    trace = Path(run["tracePath"]) if run.get("tracePath") else None
    workspace = grade.open_kept(trace) if trace and trace.exists() else None
    if workspace is not None and workspace.exists():
        kept.mkdir(parents=True, exist_ok=True)
        report = workspace / "AUDIT.md"
        if report.exists():
            shutil.copy(report, kept / "AUDIT.md")
        row["tests_pass_after"] = _tests_pass(workspace)
        status = subprocess.run([grade.GIT, "diff", "--stat", "HEAD"], cwd=workspace, capture_output=True, text=True)
        row["diff_stat"] = status.stdout.strip().split("\n")[-1] if status.stdout.strip() else "no changes"
    if (kept / "AUDIT.md").exists():
        row.update(score_audit.score_report((kept / "AUDIT.md").read_text()))
    else:
        row["report"] = "none"
    return row


def render(rows: list[dict]) -> str:
    lines = ["| Arm | Run | Located | Static | Semantic | Critical | Decoys | Tests pass after | Changed | Cost $ |", "|---|---:|---:|---:|---:|---:|---:|---|---|---:|"]
    for row in sorted(rows, key=lambda r: (r["arm"], r["run"])):
        severity = row.get("by_severity", {})
        lines.append(f"| {row['arm']} | {row['run']} | {row.get('located', '-')} | {row.get('static', '-')} | {row.get('semantic', '-')} | {severity.get('critical', '-')} | "
                     f"{row.get('decoys_flagged', '-')} | {row.get('tests_pass_after', '-')} | {row.get('diff_stat', '-')[:40]} | {row.get('cost_usd') or 0:.2f} |")
    return "\n".join(lines)


def _plugin_hash(plugin: Path = staging.PLUGIN) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in plugin.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(str(path.relative_to(plugin)).encode() + path.read_bytes())
    return digest.hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("stage", "run", "score"))
    parser.add_argument("target", help="stage: a directory. run and score: a label")
    parser.add_argument("--max-cost-usd", type=float, default=10.0)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default=os.environ.get("EVAL_MODEL", "claude-sonnet-5-5"))
    parser.add_argument("--fixture", default=FIXTURE.name, help="a folder under evals/fixtures holding repo/, ANSWERS.json and DECOYS.json")
    args = parser.parse_args()
    _use_fixture(EVALS / "fixtures" / args.fixture)
    if args.action == "stage":
        build_stage(Path(args.target))
        print(f"Staged {args.target}. Nothing was run.")
        return
    if args.action == "score":
        print(render(score(args.target)))
        return
    out = RESULTS / args.target
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    with tempfile.TemporaryDirectory(prefix="audit-stage-") as folder:
        stage_dir = Path(folder) / "stage"
        measured = _plugin_hash()  # before the stage is built: another session may change plugin/ while this runs
        build_stage(stage_dir)
        out.mkdir(parents=True)
        # Same default as run_eval.sh: on a subscription the cache otherwise lasts an hour, which costs more to write and no main thread here has outlasted 5 minutes.
        cache_ttl = os.environ.get("CLAUDE_CODE_PROMPT_CACHE_TTL", "5m")
        with open(out / "eval.log", "w") as log:
            status = subprocess.run(["claude", "plugin", "eval", str(stage_dir), "--scaffold", "--runs", str(args.runs), "--ablation", "with-without", "--keep-temp", "--no-publish",
                                     "--trust-plugin", "--model", args.model, "-j", "2", "--max-cost-usd", str(args.max_cost_usd), "--threshold", "0", "--output-dir", str(out),
                                     "--allow-tools", "Bash", "Write", "Edit"], cwd=stage_dir, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "CLAUDE_CODE_PROMPT_CACHE_TTL": cache_ttl}).returncode
        document = json.loads((out / "aggregate-result.json").read_text())
        with open(RESULTS / "ledger.jsonl", "a") as ledger:
            ledger.write(json.dumps({"step": args.target, "variant": "plugin", "ablation": "with-without", "cost_usd": document["costUsd"], "partial": document["partial"],
                                     "exit": status, "claude": document["claudeVersion"], "model": args.model, "cache_ttl": cache_ttl, "plugin_sha256": measured}) + "\n")
        print(render(score(args.target)))
        print(f"Cost ${document['costUsd']:.2f}, partial: {document['partial']}, exit {status}.")


if __name__ == "__main__":
    sys.path.insert(0, str(EVALS))
    main()
