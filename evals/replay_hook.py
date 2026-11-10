#!/usr/bin/env python3
"""What would a version of the hook do on runs already recorded? Free: nothing here calls a model or runs agent code.

    replay_hook.py [--hooks DIR] [--set GLOB ...] [--arm with|without] [--out FILE]

Feeds each saved run's tool calls through the hook's real handlers, in a temporary copy of the case with the run's final diff
applied before Stop, and counts what the hook says. A hold in the replay doesn't change the recorded run, which carries on as it
did, so this shows what fires and how often, not what an agent would have done about it. Use it to catch false holds and needless
send-backs before paying for a run. It can't show that a mechanism helps.
"""

from __future__ import annotations

import argparse
import collections
import glob
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EVALS = Path(__file__).resolve().parent
RESULTS = EVALS / "results"
DEFAULT_SETS = ("holdout-plugin", "holdout-sonnet", "python-sonnet", "python-rerun-*", "regression-fresh", "smoke-plugin", "smoke-plugin-2")
SENT_BACK = {
    "no check since the edit": "No check has run since",
    "claimed a pass": "no check passed during this turn",
    "claimed tests, no test run": "not a test run",
    "claimed all tests, filtered run": "filtered to part of the suite",
    "reviewer": "hasn't finished a review",
    "self-review not stated": "doesn't say the diff was reviewed",
    "diff not inspected": "final diff hasn't been inspected",
    "left out a failure": "doesn't mention a failure",
    "test count": "no check's output this turn contains",
    "measured change": "states a measured speedup",
    "varying result": "so its result varies",
    "unreported": "The message doesn't name",
    "scanner found new": "The scanner sees these",
    "scanner still raises": "still raises these",
    "stopped short": "part of the request wasn't done",
    "notebook can't run": "can't run top to bottom",
}


def stops_in(trace: Path) -> list[tuple[int, str]]:
    """Where the agent stopped: main-thread messages that are text with no tool call, and how many tool calls came before each."""
    messages: dict[str, dict] = {}
    seen = 0
    for line in trace.open(errors="replace"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if entry.get("type") != "assistant" or entry.get("parent_tool_use_id") or not isinstance(content, list):
            continue
        found = messages.setdefault(message.get("id") or f"line-{len(messages)}", {"text": [], "tools": False, "after": seen})
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                found["text"].append(block.get("text", ""))
            elif isinstance(block, dict) and block.get("type") == "tool_use":
                found["tools"] = True
                seen += 1
        found["after"] = seen
    return [(found["after"], "\n".join(found["text"])) for found in messages.values() if found["text"] and not found["tools"]]


def tool_calls(trace: Path) -> tuple[str, str, list[tuple[dict, dict | None]]]:
    """The run's working directory, its session id, and each main-thread tool call with its result."""
    cwd = session = ""
    calls: list[tuple[dict, dict | None]] = []
    index: dict[str, int] = {}
    for line in trace.open(errors="replace"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") == "system" and entry.get("subtype") == "init":
            # A resumed run records another `init` from wherever its shell had moved to, so the first one is the project.
            cwd, session = cwd or entry.get("cwd", ""), session or entry.get("session_id", "")
        if entry.get("parent_tool_use_id"):
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and entry.get("type") == "assistant":
                index[block["id"]] = len(calls)
                calls.append((block, None))
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in index:
                where = index[block["tool_use_id"]]
                calls[where] = (calls[where][0], block)
    return cwd, session, calls


def prompt_of(case_dir: Path) -> str:
    text = (case_dir / "prompt.md").read_text(errors="replace")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


def result_text(result: dict) -> str:
    content = result.get("content")
    return content if isinstance(content, str) else json.dumps(content)


def classify(text: str) -> list[str]:
    return [name for name, phrase in SENT_BACK.items() if phrase in text]


def hold_kind(text: str) -> str:
    lowered = text.lower()
    reference = re.search(r"occam's (\w+) reference", lowered)
    if reference:
        return f"forced read: {reference.group(1)}"
    for phrase, kind in (("skill has not been loaded", "forced read: core skill"), ("this pause happens once", "forced read: language"),
                         ("can lose or publish", "destructive git"), ("a person should confirm", "needs a person"),
                         ("reads as review-only", "read-only"), ("right after a check failed", "right after a failed check"),
                         ("removes", "weakened test"), ("skip", "weakened test")):
        if phrase in lowered:
            return kind
    return "other"


def replay_run(hook, run_dir: Path, case_dir: Path, scratch: Path) -> dict:
    """One saved run through the handlers. Paths in the record are rewritten to a temporary copy of the case."""
    cwd, session, calls = tool_calls(run_dir / "trace.jsonl")
    project = scratch / "project"
    shutil.rmtree(project, ignore_errors=True)
    shutil.copytree(case_dir / "files", project)
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    os.environ["CLAUDE_PLUGIN_DATA"] = str(scratch / "data")
    shutil.rmtree(scratch / "data", ignore_errors=True)

    def event(**fields) -> dict:
        text = json.dumps(fields)
        return {"session_id": session or "replay", "cwd": str(project), **json.loads(text.replace(cwd, str(project)) if cwd else text)}

    found: dict = {"holds": collections.Counter(), "asks": collections.Counter(), "sent_back": [], "send_backs": 0}

    patched = False

    def stop_here(text: str) -> None:
        """A send-back's reply is usually a run's last message, so judging only that one misses the send-back that caused it."""
        nonlocal patched
        patch = run_dir / "diff.patch"
        if not patched and patch.exists() and patch.read_text(errors="replace").strip():  # only the final diff is saved, so it stands in for each stop
            subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=project, capture_output=True, timeout=30, check=False)
        patched = True
        stopped = (hook.stop(event(last_assistant_message=text)) or {}).get("hookSpecificOutput") or {}
        said = classify(stopped.get("additionalContext", ""))
        found["send_backs"] += bool(stopped.get("additionalContext"))
        found["sent_back"] += [name for name in said if name not in found["sent_back"]]

    stops = stops_in(run_dir / "trace.jsonl")
    hook.user_prompt(event(prompt=prompt_of(case_dir)))
    for number, (block, result) in enumerate(calls):
        for _, text in [stop for stop in stops if stop[0] == number]:
            stop_here(text)
        call = {"tool_name": block["name"], "tool_input": block.get("input") or {}}
        output = (hook.pre_tool(event(**call)) or {}).get("hookSpecificOutput") or {}
        reason = output.get("permissionDecisionReason", "")
        if output.get("permissionDecision") == "deny":
            found["holds"][hold_kind(reason)] += 1
        elif output.get("permissionDecision") == "ask":
            found["asks"][hold_kind(reason)] += 1
        if result is None or (result.get("is_error") and "occam:" in result_text(result)[:200]):
            continue  # a hook stopped it in the recorded run, so it never ran
        if result.get("is_error"):
            hook.post_failure(event(**call, error=result_text(result)))
        else:
            hook.post_tool(event(**call, tool_response={"stdout": result_text(result)}))
            if block["name"] in ("Agent", "Task"):
                hook.subagent_stop(event(agent_id=block["id"], agent_type=str(call["tool_input"].get("subagent_type", ""))))
    last = [text for after, text in stops if after >= len(calls)]
    for text in last:
        stop_here(text)
    if not last:  # a saved run may have no message of its own at the end
        stop_here((run_dir / "final_message.txt").read_text(errors="replace") if (run_dir / "final_message.txt").exists() else "")
    return found


def replay(hooks: Path, sets: list[str], arm: str) -> list[dict]:
    sys.path.insert(0, str(hooks))
    hook = importlib.import_module("occam_hook")
    runs = []
    for pattern in sets:
        for trace in sorted(glob.glob(str(RESULTS / pattern / "graded" / "*" / f"{arm}-*" / "trace.jsonl"))):
            run_dir = Path(trace).parent
            case = run_dir.parent.name
            found = next(iter(glob.glob(str(EVALS / "cases" / "*" / case))), None)
            if not found or not (Path(found) / "files").is_dir():
                continue
            graded = json.loads((run_dir / "graded.json").read_text()) if (run_dir / "graded.json").exists() else {}
            with tempfile.TemporaryDirectory(prefix="occam-replay-") as scratch:
                result = replay_run(hook, run_dir, Path(found), Path(scratch))
            runs.append({"run": str(run_dir.relative_to(RESULTS)), "case": case, "acceptance": graded.get("acceptance"),
                         "holds": dict(result["holds"]), "asks": dict(result["asks"]), "sent_back": result["sent_back"], "send_backs": result["send_backs"]})
    return runs


def summary(runs: list[dict]) -> str:
    holds: collections.Counter = collections.Counter()
    asks: collections.Counter = collections.Counter()
    sent: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for run in runs:
        holds.update(run["holds"])
        asks.update(run["asks"])
        for name in run["sent_back"]:
            sent[name]["failing runs" if run["acceptance"] is False else "passing runs"] += 1
    total = max(1, len(runs))
    lines = [f"{len(runs)} runs. {sum(holds.values())} holds ({sum(holds.values()) / total:.2f} a run), {sum(asks.values())} asks."]
    lines += [f"  {count:4}  {kind}" for kind, count in holds.most_common()]
    lines.append(f"Sent back at Stop in {sum(1 for run in runs if run['send_backs'])} runs, {sum(run['send_backs'] for run in runs)} times. By reason (a run can have several):")
    lines += [f"  {sum(count.values()):4}  {name}: {count['failing runs']} in failing runs, {count['passing runs']} in passing runs"
              for name, count in sorted(sent.items(), key=lambda item: -sum(item[1].values()))]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hooks", type=Path, default=EVALS.parent / "plugin" / "hooks")
    parser.add_argument("--set", action="append", dest="sets", help=f"result sets, globs allowed. Default: {' '.join(DEFAULT_SETS)}")
    parser.add_argument("--arm", default="with", choices=("with", "without"))
    parser.add_argument("--out", type=Path, help="also write each run's result as JSON")
    args = parser.parse_args()
    runs = replay(args.hooks.resolve(), args.sets or list(DEFAULT_SETS), args.arm)
    if args.out:
        args.out.write_text(json.dumps(runs, indent=1))
    print(summary(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
