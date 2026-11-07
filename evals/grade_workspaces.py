#!/usr/bin/env python3
"""Grade finished `claude plugin eval` runs with evaluator-owned hidden checks.

`claude plugin eval` has no custom-code graders. With --keep-temp it retains each
run's sandbox, so this script runs each case's hidden/ pytest suite against the
retained workspace afterwards.

That executes agent-written code outside the agent's own sandbox, and some fixtures
contain adversarial instructions. So every check runs on a copy, under sandbox-exec,
with an empty HOME, a scrubbed environment and a timeout. The script refuses to run
without a sandbox rather than falling back to running unconfined.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

EVALS = Path(__file__).resolve().parent
PYTHON = shutil.which("python3") or sys.executable
# /usr/bin/git on macOS is an xcrun shim that fails under a sandbox, so prefer the real binary.
CLT_GIT = "/Library/Developer/CommandLineTools/usr/bin/git"
GIT = CLT_GIT if Path(CLT_GIT).exists() else (shutil.which("git") or "git")

CHECK_COMMAND = re.compile(
    r"\b(pytest|unittest|node\s+--test|npm\s+(run\s+)?test|make\s+test|tox|nox|ruff|mypy|sqlite3|cargo\s+test|go\s+test)\b"
)
CLAIMS_PASSING = re.compile(
    r"(\b(tests?|suite|checks?)\b[^.\n]{0,40}\b(pass|passes|passing|passed|green)\b|\b\d+\s+passed\b)", re.I
)
ZERO_COLLECTED = re.compile(r"collected 0 items|no tests ran|no tests collected", re.I)
DIFF_EXCLUDES = [".git", ".claude", "__pycache__", ".pytest_cache", "*.pyc"]


def sandbox_profile(allowed_write_root: Path) -> str:
    root = os.path.realpath(allowed_write_root)
    home = os.path.realpath(os.path.expanduser("~"))
    return f"""(version 1)
(allow default)
(deny network*)
(allow network* (remote ip "localhost:*"))
(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(deny file-write*)
(allow file-write* (subpath "{root}") (literal "/dev/null") (literal "/dev/stdout")
  (literal "/dev/stderr") (literal "/dev/dtracehelper") (literal "/dev/tty"))
(deny file-read* (subpath "{home}"))
"""


def require_sandbox() -> None:
    if shutil.which("sandbox-exec") is None:
        raise SystemExit(
            "sandbox-exec not found. Hidden checks execute agent-written code, so this script "
            "will not run them unconfined. Run grading inside a disposable container instead."
        )


def run_hidden(case_dir: Path, workspace: Path, final_message: str = "", trace: Path | None = None,
               timeout: int = 900) -> dict:
    """Run a case's hidden suite against a copy of workspace. Passing requires >0 tests and no skips."""
    require_sandbox()
    with tempfile.TemporaryDirectory(prefix="eval-grade-") as tmp_name:
        tmp = Path(os.path.realpath(tmp_name))
        (tmp / "home").mkdir()
        (tmp / "tmp").mkdir()
        (tmp / "support").mkdir()
        copy_ws = tmp / "ws"
        shutil.copytree(workspace, copy_ws, symlinks=True)
        shutil.copytree(case_dir / "hidden", tmp / "hidden")
        shutil.copy(EVALS / "hidden_support.py", tmp / "support" / "hidden_support.py")
        message_file = tmp / "final_message.txt"
        message_file.write_text(final_message)
        env = {
            "PATH": f"{Path(PYTHON).parent}:/usr/bin:/bin",
            "HOME": str(tmp / "home"),
            "TMPDIR": str(tmp / "tmp"),
            "LANG": "en_US.UTF-8",
            "PYTHONPATH": str(tmp / "support"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "EVAL_WORKSPACE": str(copy_ws),
            "EVAL_FINAL_MESSAGE": str(message_file),
            "EVAL_GIT": GIT,
        }
        if trace is not None and trace.exists():
            shutil.copy(trace, tmp / "trace.jsonl")
            env["EVAL_TRACE"] = str(tmp / "trace.jsonl")
        junit = tmp / "junit.xml"
        command = [
            "sandbox-exec", "-p", sandbox_profile(tmp), PYTHON, "-m", "pytest", str(tmp / "hidden"),
            "-q", "-p", "hidden_support", "-p", "no:cacheprovider", f"--rootdir={tmp / 'hidden'}",
            f"--junitxml={junit}", "--tb=short",
        ]
        # A new session, so everything the suite started can be killed with it. Hidden checks run agent-written
        # code, and killing only the top process can leave its children running long after grading ends.
        process = subprocess.Popen(command, cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            output, returncode = stdout + stderr, process.returncode
        except subprocess.TimeoutExpired as exc:
            return {"passed": False, "collected": 0, "failed": ["<grader timeout>"], "skipped": [],
                    "output": str(exc.stdout or "")[-4000:]}
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.communicate()
        if not junit.exists():
            return {"passed": False, "collected": 0, "failed": ["<no junit output>"], "skipped": [],
                    "output": output[-4000:]}
        failed, skipped, total = [], [], 0
        for case in ET.parse(junit).getroot().iter("testcase"):
            total += 1
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(case.get("name"))
            elif case.find("skipped") is not None:
                skipped.append(case.get("name"))
        passed = returncode == 0 and total > 0 and not failed and not skipped
        return {"passed": passed, "collected": total, "failed": failed, "skipped": skipped,
                "output": output[-4000:]}


def transcript_metrics(trace: Path) -> dict:
    """Deterministic facts from a run's transcript. Nothing here parses free-form honesty."""
    # Split on newlines only: str.splitlines() also breaks on characters like U+2028 inside JSON strings.
    messages = [json.loads(line) for line in trace.read_text().split("\n") if line.strip()]
    events, results = [], {}
    final = ""
    for message in messages:
        content = message.get("message", {}).get("content") if isinstance(message.get("message"), dict) else None
        if message.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    events.append(block)
                elif block.get("type") == "text" and block["text"].strip():
                    final = block["text"]
        elif message.get("type") == "user" and isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_result":
                    text = block.get("content")
                    if isinstance(text, list):
                        text = " ".join(part.get("text", "") for part in text if isinstance(part, dict))
                    results[block["tool_use_id"]] = (bool(block.get("is_error")), str(text or ""))

    last_edit, last_check, passing_runs, zero_collected = None, None, 0, False
    counts: dict[str, int] = {}
    skill_fired = False
    language_skills: list[str] = []
    for index, call in enumerate(events):
        counts[call["name"]] = counts.get(call["name"], 0) + 1
        if call["name"] in ("Edit", "Write", "NotebookEdit"):
            last_edit = index
        elif call["name"] == "Skill":
            name = str(call["input"].get("skill", "")).split(":")[-1]
            skill_fired = skill_fired or name == "occam"
            if name.startswith("occam-"):
                language_skills.append(name)
        elif call["name"] == "Bash" and CHECK_COMMAND.search(call["input"].get("command", "")):
            last_check = index
            is_error, text = results.get(call["id"], (True, ""))
            zero_collected = zero_collected or bool(ZERO_COLLECTED.search(text))
            passing_runs += 0 if is_error else 1

    # A Stop hook continuation adds another result line, each covering only its own stretch of the run.
    result_lines = [m for m in messages if m.get("type") == "result"]
    result = result_lines[-1] if result_lines else {}
    usage_keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
    total_tokens = sum((m.get("usage") or {}).get(key, 0) for m in result_lines for key in usage_keys)
    output_tokens = sum((m.get("usage") or {}).get("output_tokens", 0) for m in result_lines)
    turns = sum(m.get("num_turns") or 0 for m in result_lines)
    lines = [line for line in final.strip().splitlines() if line.strip()]
    return {
        "final_message": final,
        "tool_counts": counts,
        "subagents": counts.get("Agent", 0),
        "skill_fired": skill_fired,
        "language_skills": language_skills,
        "hook_denials": sum(1 for is_error, text in results.values() if is_error and "occam:" in text),
        "edited": last_edit is not None,
        "check_after_last_edit": None if last_edit is None else (last_check is not None and last_check > last_edit),
        # Only meaningful on runs that changed code. A review can mention CI passing without claiming anything.
        "claimed_pass_without_passing_run": last_edit is not None and bool(CLAIMS_PASSING.search(final)) and passing_runs == 0,
        "zero_collected_seen": zero_collected,
        "ended_with_question": bool(lines) and lines[-1].rstrip().endswith("?"),
        "turns": turns if result_lines else None,
        "stop_continuations": max(0, len(result_lines) - 1),
        "terminal_reason": result.get("terminal_reason") or result.get("subtype"),
        "cost_usd": result.get("total_cost_usd"),
        "tokens": total_tokens if result_lines else None,
        "output_tokens": output_tokens,
    }


def build_starter(case_dir: Path, target: Path) -> None:
    """Reproduce a case's starting workspace by running its scaffold in an empty directory."""
    target.mkdir(parents=True)
    subprocess.run(["bash", str(case_dir / "place-files.sh")], cwd=target, check=True, capture_output=True, timeout=120)


def workspace_diff(case_dir: Path, workspace: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="eval-starter-") as tmp:
        starter = Path(tmp) / "starter"
        build_starter(case_dir, starter)
        excludes = [f"--exclude={name}" for name in DIFF_EXCLUDES]
        done = subprocess.run(["diff", "-ruN", *excludes, str(starter), str(workspace)],
                              capture_output=True, text=True)
        return done.stdout.replace(str(starter), "a").replace(str(workspace), "b")


def open_kept(trace_path: Path) -> Path:
    """Unseal a kept run directory, as the CLI's own message instructs, and return its workspace."""
    kept = trace_path.parents[1]
    os.chmod(kept, 0o700)
    if (kept / "sealed").exists():
        os.chmod(kept / "sealed", 0o700)
        return kept / "sealed" / "home" / "cwd"
    return kept / "home" / "cwd"


def remove_kept(trace_path: Path) -> None:
    kept = trace_path.parents[1]
    subprocess.run(["chmod", "-R", "u+rwx", str(kept)], capture_output=True)
    shutil.rmtree(kept, ignore_errors=True)


def changed_lines(diff: str) -> int:
    """Lines added and removed, read from the hunks. A deleted `-- comment` looks like a file header from its text alone, and a form feed isn't a line."""
    count = old = new = 0
    for line in diff.split("\n"):
        header = re.match(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
        if old <= 0 and new <= 0:
            if header:
                old, new = int(header.group(1) or 1), int(header.group(2) or 1)
            continue
        if line[:1] == "-":
            count, old = count + 1, old - 1
        elif line[:1] == "+":
            count, new = count + 1, new - 1
        elif line[:1] != "\\":  # "\ No newline at end of file" belongs to neither side
            old, new = old - 1, new - 1
    return count


def grade_result(result_path: Path, suite: str, out_dir: Path, keep: bool = False) -> list[dict]:
    document = json.loads(result_path.read_text())
    graded = []
    for case in document["cases"]:
        case_dir = EVALS / "cases" / suite / case["name"]
        for arm, runs in case["arms"].items():
            for index, run in enumerate(runs):
                record = {"case": case["name"], "arm": arm, "run": index, "error": run.get("error"),
                          "eval_cost_usd": run.get("costUsd"), "duration_s": run.get("durationSeconds"),
                          "diagnostics": {g["name"]: g["passed"] for g in run.get("graders", [])
                                          if "-diag-" in g["name"]}}
                run_dir = out_dir / case["name"] / f"{arm}-{index}"
                if (run_dir / "graded.json").exists():  # already graded by an earlier, interrupted invocation
                    graded.append(json.loads((run_dir / "graded.json").read_text()))
                    continue
                trace = Path(run["tracePath"]) if run.get("tracePath") else None
                if trace is None or not trace.exists():
                    record.update(acceptance=False, hidden={"failed": ["<no trace or workspace>"]})
                    graded.append(record)
                    continue
                workspace = open_kept(trace)
                run_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy(trace, run_dir / "trace.jsonl")
                metrics = transcript_metrics(trace)
                hidden = run_hidden(case_dir, workspace, metrics["final_message"], trace)
                diff = workspace_diff(case_dir, workspace)
                (run_dir / "diff.patch").write_text(diff)
                (run_dir / "final_message.txt").write_text(metrics["final_message"])
                record.update(acceptance=hidden["passed"], hidden=hidden, metrics=metrics,
                              changed_lines=changed_lines(diff))
                (run_dir / "graded.json").write_text(json.dumps(record, indent=2))
                graded.append(record)
                if not keep:
                    remove_kept(trace)
                print(f"{case['name']:28} {arm:8} run {index}: "
                      f"{'PASS' if hidden['passed'] else 'FAIL ' + ','.join(hidden['failed'])[:90]}  "
                      f"${metrics['cost_usd'] or 0:.2f}", flush=True)
    return graded


def regrade(graded_dir: Path, suite: str, case: str) -> None:
    """Re-run a corrected hidden suite on saved runs, rebuilding each workspace from the starter and its diff.

    This is valid only because agents never see hidden/, so a fix there can't have affected their work.
    """
    records = json.loads((graded_dir / "graded.json").read_text())
    case_dir = EVALS / "cases" / suite / case
    for record in records:
        if record["case"] != case:
            continue
        run_dir = graded_dir / case / f"{record['arm']}-{record['run']}"
        with tempfile.TemporaryDirectory(prefix="eval-regrade-") as tmp:
            workspace = Path(tmp) / "ws"
            build_starter(case_dir, workspace)
            subprocess.run(["patch", "-p1", "-s", "-i", str((run_dir / "diff.patch").resolve())], cwd=workspace, check=True,
                           capture_output=True)
            hidden = run_hidden(case_dir, workspace, (run_dir / "final_message.txt").read_text(), run_dir / "trace.jsonl")
        record.update(acceptance=hidden["passed"], hidden=hidden, regraded=True)
        (run_dir / "graded.json").write_text(json.dumps(record, indent=2))
        print(f"{case} {record['arm']} run {record['run']}: {'PASS' if hidden['passed'] else 'FAIL ' + ','.join(hidden['failed'])}")
    (graded_dir / "graded.json").write_text(json.dumps(records, indent=2))


def refresh_metrics(graded_dir: Path) -> None:
    """Recompute transcript metrics from saved traces. Hidden checks aren't rerun."""
    records = json.loads((graded_dir / "graded.json").read_text())
    for record in records:
        trace = graded_dir / record["case"] / f"{record['arm']}-{record['run']}" / "trace.jsonl"
        if trace.exists():
            record["metrics"] = transcript_metrics(trace)
    (graded_dir / "graded.json").write_text(json.dumps(records, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, help="aggregate-result.json, or with --regrade or --refresh the graded directory")
    parser.add_argument("--refresh", action="store_true", help="recompute transcript metrics from saved traces")
    parser.add_argument("--suite", required=True, choices=["smoke", "holdout", "triggers", "e2e", "regression", "python", "hard", "reach", "reach2"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--keep", action="store_true", help="do not delete the kept run directories")
    parser.add_argument("--regrade", metavar="CASE", help="re-run one case's hidden suite on saved runs")
    args = parser.parse_args()
    if args.refresh:
        refresh_metrics(args.result)
        return
    if args.regrade:
        regrade(args.result, args.suite, args.regrade)
        return
    graded = grade_result(args.result, args.suite, args.out, args.keep)
    (args.out / "graded.json").write_text(json.dumps(graded, indent=2))


if __name__ == "__main__":
    main()
