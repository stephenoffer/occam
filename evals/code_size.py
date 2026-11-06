#!/usr/bin/env python3
"""How much code each arm delivered, from the diffs saved with graded runs. Reads results only, and costs nothing.

    code_size.py [--accepted-only] [--against SUITE] SUITE ...

Compares arm `with` against arm `without` in each suite's graded.json, or against the `without` arm of --against for a suite
that ran alone. Prints medians per case, then a geometric mean across cases. Source lines added and gzip size of those lines
are both shown, because line counts reward dense code and gzip rewards it less.

Smaller is not better by itself: a run stopped at the time limit also delivers less, which is what --accepted-only is for.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import NamedTuple

RESULTS = Path(__file__).resolve().parent / "results"
TEST_PATH = re.compile(r"(^|/)(tests?|spec|__tests__|hidden)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$|conftest\.py$")
CODE_PATH = re.compile(r"\.(py|ts|tsx|js|jsx|go|rs|java|kt|sql|sh|c|cc|cpp|h)$")
FINISHED = (None, "success", "completed")


class Size(NamedTuple):
    source_added: int
    test_added: int
    gzip_bytes: int


def measure(patch: str) -> Size:
    """Lines added to code files in a `diff -ruN` patch, with tests counted apart from source."""
    source: list[str] = []
    tests = 0
    path = None
    previous = ""
    for line in patch.splitlines():
        is_header = line.startswith("+++ ") and previous.startswith("--- ")  # an added `++ i;` also starts "+++ ", but no "--- " comes before it
        previous = line
        if is_header:
            token = line[4:].split("\t")[0].strip()
            path = token.split("/", 1)[1] if "/" in token else token
        elif line.startswith("+") and path and CODE_PATH.search(path):
            if TEST_PATH.search(path):
                tests += 1
            else:
                source.append(line[1:])
    packed = len(gzip.compress("\n".join(source).encode(), mtime=0)) if source else 0
    return Size(len(source), tests, packed)


def load_runs(suite: str, arm: str, results: Path = RESULTS) -> list[dict]:
    base = results / suite / "graded"
    runs = []
    for record in json.loads((base / "graded.json").read_text()):
        patch = base / record["case"] / f"{record['arm']}-{record['run']}" / "diff.patch"
        text = patch.read_text(errors="replace") if patch.exists() else ""
        if record["arm"] == arm and text.strip():
            finished = not record.get("error") and (record.get("metrics") or {}).get("terminal_reason") in FINISHED
            runs.append({"case": record["case"], "accepted": bool(record.get("acceptance")) and finished, "cost": record.get("eval_cost_usd") or 0.0, "size": measure(text)})
    return runs


def by_case(runs: list[dict], accepted_only: bool) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for run in runs:
        if run["accepted"] or not accepted_only:
            grouped.setdefault(run["case"], []).append(run)
    return grouped


def geometric_mean(values: list[float]) -> float:
    return math.exp(statistics.mean(math.log(value) for value in values))


def compare(name: str, with_runs: list[dict], without_runs: list[dict], accepted_only: bool) -> list[str]:
    arm, baseline = by_case(with_runs, accepted_only), by_case(without_runs, accepted_only)
    lines = [f"## {name}{' (accepted, finished runs only)' if accepted_only else ''}", "", "| Case | Runs | Source lines | Test lines | Gzip bytes | Mean cost $ |", "|---|---:|---:|---:|---:|---:|"]
    ratios = []
    unmeasured = []

    def middle(field: str, runs: list[dict]) -> float:
        return statistics.median(getattr(run["size"], field) for run in runs)

    if not set(arm) & set(baseline):
        lines.append(f"| No case has runs in both arms, so nothing compares here. Arm: {len(arm)} cases, baseline: {len(baseline)}. Use --against for a suite that ran alone. | | | | | |")
    for case in sorted(set(arm) & set(baseline)):
        cost = [statistics.mean(run["cost"] for run in side[case]) for side in (arm, baseline)]
        lines.append(f"| {case} | {len(arm[case])}/{len(baseline[case])} | {middle('source_added', arm[case]):.0f}/{middle('source_added', baseline[case]):.0f} "
                     f"| {middle('test_added', arm[case]):.0f}/{middle('test_added', baseline[case]):.0f} | {middle('gzip_bytes', arm[case]):.0f}/{middle('gzip_bytes', baseline[case]):.0f} | {cost[0]:.2f}/{cost[1]:.2f} |")
        if middle("source_added", arm[case]) and middle("source_added", baseline[case]) and all(cost):
            ratios.append((middle("source_added", arm[case]) / middle("source_added", baseline[case]), middle("gzip_bytes", arm[case]) / middle("gzip_bytes", baseline[case]), cost[0] / cost[1]))
        else:
            unmeasured.append(case)  # no source lines or no cost on one side, which a notebook-only change shows as 0/0
    if ratios:
        lines += ["", f"Arm over baseline across {len(ratios)} cases: source lines {geometric_mean([r[0] for r in ratios]):.2f}, gzip {geometric_mean([r[1] for r in ratios]):.2f}, cost {geometric_mean([r[2] for r in ratios]):.2f}. "
                      f"Smaller on {sum(r[0] < 1 for r in ratios)}, larger on {sum(r[0] > 1 for r in ratios)}."]
    if unmeasured:
        lines += ["", f"Left out of that ratio, with no source lines or cost to compare: {', '.join(unmeasured)}."]
    return [*lines, ""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("suites", nargs="+")
    parser.add_argument("--accepted-only", action="store_true")
    parser.add_argument("--against", help="take the no-skill runs from this suite")
    args = parser.parse_args(argv)
    missing = [suite for suite in [*args.suites, args.against] if suite and not (RESULTS / suite / "graded" / "graded.json").exists()]
    if missing:
        print(f"No graded runs for: {', '.join(missing)}", file=sys.stderr)
        return 2
    for suite in args.suites:
        baseline = load_runs(args.against or suite, "without")
        print("\n".join(compare(suite, load_runs(suite, "with"), baseline, args.accepted_only)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
