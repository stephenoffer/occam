#!/usr/bin/env python3
"""Codex adapter smoke: does the skill get discovered, fire, stay read-only, and handle one fix?

This is not a comparison and makes no quality claim. It uses `codex exec`, billed to your own
Codex plan, in disposable workspaces with the skill installed at <workspace>/.agents/skills/.
It reuses the same starting repositories and hidden checks as the Claude runs.

    CODEX_BIN=/path/to/codex evals/codex_smoke.py --out evals/results/codex-smoke
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import grade_workspaces as grade

EVALS = Path(__file__).resolve().parent
SKILLS = EVALS.parent / "plugin" / "skills"
SKILL_MARKER = "skills/occam/SKILL.md"
CHECKS = [
    # name, suite, case, expect the skill to fire, run hidden checks
    ("implicit-fix", "smoke", "sync-adapter-bug", True, True),
    ("read-only-review", "smoke", "review-with-injection", True, True),
    ("near-miss-negative", "triggers", "neg-mutex-vs-semaphore", False, False),
]


def prompt_of(case_dir: Path) -> str:
    return (case_dir / "prompt.md").read_text().split("---", 2)[2].strip()


def prepare(case_dir: Path, workspace: Path) -> None:
    if (case_dir.parent / "_shared_repo").is_dir():
        workspace.mkdir(parents=True)
        shutil.copytree(case_dir.parent / "_shared_repo", workspace, dirs_exist_ok=True)
        subprocess.run([grade.GIT, "init", "-q", "."], cwd=workspace, check=True)
    else:
        grade.build_starter(case_dir, workspace)
    shutil.copytree(SKILLS, workspace / ".agents" / "skills")
    # The installed skill should not look like a change the agent made.
    with open(workspace / ".git" / "info" / "exclude", "a") as handle:
        handle.write(".agents/\n")


def to_claude_trace(events: list[dict], path: Path) -> None:
    """Hidden checks read a Claude-shaped trace, so map Codex command executions onto it."""
    with open(path, "w") as handle:
        for event in events:
            item = event.get("item") or {}
            if event.get("type") == "item.started" and item.get("type") == "command_execution":
                block = {"type": "tool_use", "id": item.get("id", ""), "name": "Bash",
                         "input": {"command": item.get("command", "")}}
                handle.write(json.dumps({"type": "assistant", "message": {"content": [block]}}) + "\n")


def run_check(codex: str, model: str, name: str, suite: str, case: str, expect_fired: bool, use_hidden: bool, out: Path) -> dict:
    case_dir = EVALS / "cases" / suite / case
    with tempfile.TemporaryDirectory(prefix="codex-smoke-") as tmp:
        workspace = Path(os.path.realpath(tmp)) / "ws"
        prepare(case_dir, workspace)
        final_file = Path(tmp) / "final.txt"
        command = [codex, "exec", "--json", "--ephemeral", "--ignore-user-config", "-m", model,
                   "-s", "workspace-write", "-C", str(workspace), "-o", str(final_file), prompt_of(case_dir)]
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=900)
            stdout, stderr, returncode = done.stdout, done.stderr, done.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, returncode = str(exc.stdout or ""), "timed out", -1
        events = []
        for line in stdout.split("\n"):
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        fired = SKILL_MARKER in stdout
        final = final_file.read_text() if final_file.exists() else ""
        record = {"name": name, "case": case, "returncode": returncode, "fired": fired,
                  "fired_as_expected": fired == expect_fired, "final_message": final,
                  "stderr_tail": stderr[-600:]}
        if returncode != 0:
            record["status"] = "blocked"
        elif use_hidden:
            trace = Path(tmp) / "trace.jsonl"
            to_claude_trace(events, trace)
            hidden = grade.run_hidden(case_dir, workspace, final, trace)
            record.update(status="verified" if hidden["passed"] else "failed", hidden=hidden)
        else:
            record["status"] = "verified"
        (out / f"{name}.jsonl").write_text(stdout)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default="gpt-5.3-codex")
    parser.add_argument("--only", help="run one check by name")
    args = parser.parse_args()
    codex = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if not codex:
        raise SystemExit("Codex CLI not found. Set CODEX_BIN.")
    version = subprocess.run([codex, "--version"], capture_output=True, text=True).stdout.strip()
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    for name, suite, case, expect_fired, use_hidden in CHECKS:
        if args.only and name != args.only:
            continue
        record = run_check(codex, args.model, name, suite, case, expect_fired, use_hidden, args.out)
        records.append(record)
        print(f"{name:22} status={record['status']:9} fired={record['fired']} (expected {expect_fired})", flush=True)
        if record["status"] == "blocked":
            print(record["stderr_tail"], flush=True)
            break
    (args.out / "results.json").write_text(json.dumps({"codex": version, "model": args.model, "records": records}, indent=2))


if __name__ == "__main__":
    main()
