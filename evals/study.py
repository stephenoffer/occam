#!/usr/bin/env python3
"""The audit study in evals/PREREGISTRATION.md: net verified repair, with the fixture as the unit.

    study.py freeze                 copy plugin/ once, so all fixtures measure one version
    study.py pilot FIXTURE          billed: one no-skill run, to check the fixture has room for a gain
    study.py run FIXTURE            billed: 3 runs per arm. Refuses if the spend so far plus a reserve would pass the cap
    study.py score LABEL            net score for each run in results/LABEL, by running its hidden checks
    study.py report                 per-fixture differences, signed-rank test and estimate

A fixture holds repo/, oracles/, ITEMS.json and DECOYS.json. An item's "checks" name every test that must pass. Decision and false-claim matching use its "topic": groups of terms, one needed from each. A status of "fixed" also has to be at the item's place.
A check's outcome comes from running it, so writing or citing more earns nothing.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

import audit_comparison as harness
import grade_workspaces as grade
import oracle_score as oracles
import stage as staging

EVALS = Path(__file__).resolve().parent
STUDY = EVALS / "results" / "study"
FROZEN = STUDY / "plugin"
CAP_USD = 225.0  # the audit study's share of the $300 approved. The new-code test holds the other $75
TOTAL_CAP_USD = 300.0
RESERVE_USD = 45.0  # the most one fixture's 6 runs have been seen to cost, with room to spare
WEIGHT = 3  # the user's choice: one new bug costs three fixes
PROMPT = """---
tags: [audit]
max_turns: 150
timeout_seconds: 2700
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Edit, Bash]
---

This service was mostly written by an AI assistant and we're about to put real customers on it. Audit it and fix what you can.

Bringing code in line with its documentation is in scope. Anything else that changes behavior goes in a decisions section with your recommendation, since nobody is available to answer questions during this run.

Write AUDIT.md at the repository root for the people who own this: what you found, what you fixed and what you need decided. Beside it write AUDIT.jsonl, with one JSON object per problem: {"file": ..., "line": ..., "function": ..., "severity": "critical|high|medium|low", "status": "fixed|open|decision", "what": ...}. Use line numbers from the original code. Don't commit.
"""


def spent(prefix: str = "study-") -> float:
    """Billed spend so far, from the ledger every run writes to. study-0 is the audit study and study-newcode the new-code test."""
    rows = [json.loads(line) for line in (EVALS / "results" / "ledger.jsonl").read_text().splitlines() if line.strip()]
    return sum(row.get("cost_usd") or 0 for row in rows if str(row.get("step", "")).startswith(prefix))


def may_start(spend: float, cap: float = CAP_USD, reserve: float = RESERVE_USD) -> bool:
    return spend + reserve <= cap


def _bill(label: str, fixture: str, runs: int, plugin: Path | None) -> None:
    if not (may_start(spent("study-0")) and may_start(spent(), TOTAL_CAP_USD)):
        raise SystemExit(f"stopping: ${spent('study-0'):.2f} on this study and ${spent():.2f} in all, and another fixture could pass a cap. Report the rest as not run.")
    if plugin and not FROZEN.exists():
        raise SystemExit("run `study.py freeze` first")
    out = EVALS / "results" / label
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    harness._use_fixture(EVALS / "fixtures" / fixture)
    with tempfile.TemporaryDirectory(prefix="study-stage-") as folder:
        stage = Path(folder) / "stage"
        harness.build_stage(stage, plugin=plugin, prompt=PROMPT)
        out.mkdir(parents=True)
        command = ["caffeinate", "-ims", "claude", "plugin", "eval", str(stage), "--scaffold", "--runs", str(runs), "--ablation", "with-without" if plugin else "none",
                   "--keep-temp", "--no-publish", "--trust-plugin", "--model", "claude-sonnet-5-5", "-j", "2", "--max-cost-usd", str(RESERVE_USD), "--threshold", "0",
                   "--output-dir", str(out), "--allow-tools", "Bash", "Write", "Edit"]
        with open(out / "eval.log", "w") as log:
            status = subprocess.run(command, cwd=stage, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "CLAUDE_CODE_PROMPT_CACHE_TTL": "5m"}).returncode
    document = json.loads((out / "aggregate-result.json").read_text())
    with open(EVALS / "results" / "ledger.jsonl", "a") as ledger:
        ledger.write(json.dumps({"step": label, "fixture": fixture, "variant": "plugin" if plugin else "empty", "cost_usd": document["costUsd"], "partial": document["partial"], "exit": status,
                                 "claude": document["claudeVersion"], "model": "claude-sonnet-5-5", "plugin_sha256": harness._plugin_hash(plugin) if plugin else None}) + "\n")
    print(f"{label}: ${document['costUsd']:.2f}, partial {document['partial']}, exit {status}. Study total ${spent():.2f}.")


def on_topic(row: dict, item: dict) -> bool:
    """Is this report row about this item? One term from each of the item's groups, in a package where it could sensibly be raised. A place alone isn't enough, since a row can ask something else about the same function. The file is only for the package: its path would answer a group by itself, for every row in that package."""
    groups = item.get("topic") or []
    text = " ".join(str(row.get(field, "")) for field in ("what", "function")).lower()
    where = str(row.get("file") or "")
    in_place = not item.get("packages") or any(package in where for package in item["packages"])
    return bool(groups) and in_place and all(any(term.lower() in text for term in group) for group in groups)


def same_place(row: dict, item: dict) -> bool:
    """Does this row name one of the item's functions, or sit in its file within 15 lines of it?"""
    named = set(re.findall(r"\w+", f"{row.get('function', '')} {row.get('what', '')}"))
    if named & set(item.get("functions") or [item.get("function")]):
        return True
    try:
        near = abs(int(row.get("line")) - int(item.get("line"))) <= 15
    except (TypeError, ValueError):
        return False
    where = str(row.get("file") or "")
    return near and bool(item.get("file")) and (where == item["file"] or where.endswith("/" + item["file"]))  # not another folder's file of that name


def raised(rows: list[dict], item: dict) -> bool:
    return any(row.get("status") == "decision" and on_topic(row, item) for row in rows)


def raised_once(rows: list[dict], items: list[dict]) -> set[str]:
    """The items a report raised as decisions, each row counting for one item at most, so one row in a package can't be credit for
    every decision there. Rows are assigned so that as many items as possible get one."""
    decisions = [index for index, row in enumerate(rows) if row.get("status") == "decision"]
    fits = {item["id"]: [index for index in decisions if on_topic(rows[index], item)] for item in items}
    taken: dict[int, str] = {}  # row -> item, grown by augmenting paths, so the most items get a row of their own

    def place(item_id: str, seen: set[int]) -> bool:
        for index in fits[item_id]:
            if index not in seen:
                seen.add(index)
                if index not in taken or place(taken[index], seen):
                    taken[index] = item_id
                    return True
        return False
    return {item["id"] for item in items if place(item["id"], set())}


def claimed_fixed(rows: list[dict], item: dict) -> bool:
    """A status the checks can contradict needs more than shared words: the row has to be at the item's place too."""
    return any(row.get("status") == "fixed" and on_topic(row, item) and same_place(row, item) for row in rows)


def regressions(causes: list[dict]) -> int:
    """Distinct packages with newly failing tests. Counting by test or frame lets one changed line look like many bugs, and at 3 fixes each that decides results.
    This errs against the plugin's earlier advantage: two separate bugs in one package count once."""
    def package(frame: str) -> str:
        parts = frame.split(":")[0].split("/")
        return parts[1] if len(parts) > 2 else parts[0]
    return len({package(cause["frame"]) for cause in causes})


def passes(item: dict, outcome: dict[str, bool]) -> bool:
    """An item counts only if every test in its check passes, including the behavior test beside a structural one."""
    return all(outcome.get(_test_name(check)) for check in item["checks"])


def net(passed: int, decisions: int, regressions: int, items: int, weight: int = WEIGHT) -> float:
    return (passed + decisions - weight * regressions) / items


def _test_name(check: str) -> str:
    return check.rsplit("::", 1)[-1]


def attempt_diff(workspace: Path) -> str:
    """What the attempt changed. The fixture's own tests go back over any attempt, so its test edits are left out, and they can't stop the rest applying."""
    subprocess.run([grade.GIT, "add", "-A", "-N", "."], cwd=workspace, capture_output=True)
    return subprocess.run([grade.GIT, "diff", "HEAD", "--", ".", ":(exclude)AUDIT.md", ":(exclude)AUDIT.jsonl", ":(exclude)tests"], cwd=workspace, capture_output=True, text=True).stdout


def score_run(fixture: Path, workspace: Path, baseline: set[str], timeout: int = 600) -> dict:
    """What one attempt's final code does under the hidden checks, its fixture's original tests and the preservation tests."""
    items = json.loads((fixture / "ITEMS.json").read_text())
    decoys = json.loads((fixture / "DECOYS.json").read_text())
    diff = attempt_diff(workspace)
    report = workspace / "AUDIT.jsonl"
    rows = []
    for line in (report.read_text().splitlines() if report.exists() else []):
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    with oracles.scratch() as root:
        (root / "agent.diff").write_text(diff)
        prepared, problem = oracles.prepare_workspace(fixture, root, root / "agent.diff" if diff.strip() else None)
        if problem:
            return {"error": problem}
        hidden, suite = oracles.run_pytest(prepared, "oracles", root, timeout), oracles.run_pytest(prepared, "tests", root, timeout)
        if hidden["error"] or suite["error"]:
            return {"error": hidden["error"] or suite["error"]}
        outcome = {case["name"]: case["outcome"] == "passed" for case in hidden["cases"].values()}
        repairs = [item for item in items if item["class"] != "decision"]
        passed = [item["id"] for item in repairs if passes(item, outcome)]
        decisions = [item for item in items if item["class"] == "decision"]
        changed = {item["id"] for item in decisions if not passes(item, outcome)}  # a decision's check pins today's behavior
        flagged = {item["id"] for item in decisions if claimed_fixed(rows, item)}
        raised_ids = raised_once(rows, decisions)
        decided = [item["id"] for item in decisions if item["id"] in raised_ids or (item["id"] in changed and item["id"] in flagged)]
        unflagged = sorted(changed - set(decided))
        preserved = {_test_name(decoy["check"]) for decoy in decoys}
        broken = {name: (case["text"], case["log"]) for name, case in hidden["cases"].items() if case["name"] in preserved and case["outcome"] == "failed"}
        broken.update({name: (case["text"], case["log"]) for name, case in suite["cases"].items() if case["outcome"] == "failed" and name not in baseline})
        causes = oracles.root_causes(broken, prepared)
    false_claims = [item["id"] for item in repairs if item["id"] not in passed and claimed_fixed(rows, item)]
    by_class = {name: sum(item["class"] == name for item in items) for name in ("serious", "maintainability", "decision")}
    record = {"items": len(items), "passed": passed, "decisions": decided, "unflagged_decisions": unflagged, "root_causes": causes, "regressions": regressions(causes), "failing_tests": len(broken), "false_claims": false_claims,
              "decoys_broken": sorted(_test_name(name) for name in broken if _test_name(name) in preserved), "report_rows": len(rows),
              "share_serious": sum(item["class"] == "serious" and item["id"] in passed for item in items) / max(by_class["serious"], 1),
              "share_maintainability": sum(item["class"] == "maintainability" and item["id"] in passed for item in items) / max(by_class["maintainability"], 1),
              "share_decision": len(decided) / max(by_class["decision"], 1)}
    for weight in (1, 2, 3):
        record[f"net_w{weight}"] = net(len(passed), len(decided), record["regressions"], len(items), weight)
    return record


def score(label: str) -> list[dict]:
    out = EVALS / "results" / label
    document = json.loads((out / "aggregate-result.json").read_text())
    fixture = EVALS / "fixtures" / label.split("-run")[0].split("-pilot")[0]
    baseline = {name for name, case in oracles.run_on_start(fixture, "tests", 600)["cases"].items() if case["outcome"] == "failed"}
    rows = []
    for arm, runs in document["cases"][0]["arms"].items():
        for index, run in enumerate(runs):
            workspace = grade.open_kept(Path(run["tracePath"]))
            row = {"arm": "no-skill" if label.endswith("-pilot") else arm, "run": index, "cost_usd": run.get("costUsd"), "seconds": run.get("durationSeconds"), "error_run": run.get("error")}
            row.update(score_run(fixture, workspace, baseline))
            kept = out / "reports" / f"{arm}-{index}"
            kept.mkdir(parents=True, exist_ok=True)
            for name in ("AUDIT.md", "AUDIT.jsonl"):
                if (workspace / name).exists():
                    shutil.copy(workspace / name, kept / name)
            rows.append(row)
    (out / "net.json").write_text(json.dumps(rows, indent=2) + "\n")
    return rows


def signed_rank_p(differences: list[float]) -> float:
    """Exact two-sided Wilcoxon signed-rank p, from every sign assignment. Zeros are dropped, and ties share ranks."""
    values = [d for d in differences if d != 0]
    if not values:
        return 1.0
    ordered = sorted(abs(v) for v in values)
    rank = {size: statistics.mean(i + 1 for i, other in enumerate(ordered) if other == size) for size in set(ordered)}
    ranks = [rank[abs(v)] for v in values]
    observed = sum(r for r, v in zip(ranks, values) if v > 0)
    middle = sum(ranks) / 2
    totals = [sum(r for r, sign in zip(ranks, signs) if sign) for signs in itertools.product((0, 1), repeat=len(ranks))]
    return sum(abs(total - middle) >= abs(observed - middle) for total in totals) / len(totals)


def hodges_lehmann(differences: list[float]) -> float:
    return statistics.median((a + b) / 2 for i, a in enumerate(differences) for b in differences[i:])


def fixture_difference(rows: list[dict], key: str = f"net_w{WEIGHT}") -> dict:
    values = {arm: [row[key] for row in rows if row["arm"] == arm and key in row] for arm in ("with", "without")}
    medians = {arm: statistics.median(found) if found else None for arm, found in values.items()}
    gap = medians["with"] - medians["without"] if None not in medians.values() else None
    return {"values": values, "medians": medians, "difference": gap}


def report() -> dict:
    done = sorted(path for path in (EVALS / "results").glob("study-*-run/net.json"))
    keys = {"w1": "net_w1", "w2": "net_w2", "w3": "net_w3", "serious": "share_serious", "maintainability": "share_maintainability", "decision": "share_decision"}
    table = {path.parent.name: {name: fixture_difference(json.loads(path.read_text()), key) for name, key in keys.items()} for path in done}
    primary = [row["w3"]["difference"] for row in table.values() if row["w3"]["difference"] is not None]
    summary = {"fixtures": table, "n": len(primary), "spent_usd": round(spent(), 2)}
    if primary:
        summary.update(mean=statistics.mean(primary), estimate=hodges_lehmann(primary), p=signed_rank_p(primary), futility_after_4=len(primary) >= 4 and statistics.mean(primary[:4]) <= 0)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("freeze", "pilot", "run", "score", "report"))
    parser.add_argument("target", nargs="?")
    args = parser.parse_args()
    if args.action == "freeze":
        if FROZEN.exists():
            raise SystemExit(f"already frozen at {harness._plugin_hash(FROZEN)}")
        ignored = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        for part in ("skills", "hooks", "agents"):
            shutil.copytree(staging.PLUGIN / part, FROZEN / part, ignore=ignored)
        print(harness._plugin_hash(FROZEN))
    elif args.action == "pilot":
        _bill(f"{args.target}-pilot", args.target, 1, None)
    elif args.action == "run":
        _bill(f"{args.target}-run", args.target, 3, FROZEN)
    elif args.action == "score":
        print(json.dumps(score(args.target), indent=1)[:4000])
    else:
        print(json.dumps(report(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
