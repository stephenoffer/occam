#!/usr/bin/env python3
"""Summarize graded runs. Reports raw counts per case: no significance claims.

    summarize.py --label with-skill=path/graded.json ... [--blind-out DIR]

The primary outcome is one pass/fail per case per run. Everything else is a diagnostic,
reported separately so it can't quietly become the headline.
"""

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path


def mean(values):
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


def fmt(value, spec=".0f"):
    return "-" if value is None else format(value, spec)


def table(runs):
    rows = ["| Case | Arm | Acceptance | Tokens (mean) | Cost $ (mean) | Time s (mean) | Fired | Subagents | Check after last edit | Truncated | Ended asking | Changed lines (mean) |",
            "|---|---|---|---:|---:|---:|---|---:|---|---|---|---:|"]
    groups = defaultdict(list)
    for run in runs:
        groups[(run["case"], run["arm"])].append(run)
    for (case, arm), group in sorted(groups.items()):
        metrics = [run.get("metrics") or {} for run in group]
        edited = [m for m in metrics if m.get("edited")]
        truncated = sum(1 for run in group if run.get("error") or (run.get("metrics") or {}).get("terminal_reason") not in (None, "success", "completed"))
        rows.append("| " + " | ".join([
            case, arm,
            f"{sum(1 for run in group if run.get('acceptance'))}/{len(group)}",
            fmt(mean([m.get("tokens") for m in metrics])),
            fmt(mean([run.get("eval_cost_usd") for run in group]), ".2f"),
            fmt(mean([run.get("duration_s") for run in group])),
            f"{sum(1 for m in metrics if m.get('skill_fired'))}/{len(group)}",
            fmt(mean([m.get("subagents") for m in metrics]), ".1f"),
            f"{sum(1 for m in edited if m.get('check_after_last_edit'))}/{len(edited)}",
            f"{truncated}/{len(group)}",
            f"{sum(1 for m in metrics if m.get('ended_with_question'))}/{len(group)}",
            fmt(mean([run.get("changed_lines") for run in group])),
        ]) + " |")
    return "\n".join(rows)


def totals(runs):
    groups = defaultdict(list)
    for run in runs:
        groups[run["arm"]].append(run)
    lines = ["| Arm | Runs | Acceptance | Claimed pass with no passing run | Zero-collected seen | Total cost $ |", "|---|---:|---|---:|---:|---:|"]
    for arm, group in sorted(groups.items()):
        metrics = [run.get("metrics") or {} for run in group]
        lines.append(f"| {arm} | {len(group)} | {sum(1 for r in group if r.get('acceptance'))}/{len(group)} | "
                     f"{sum(1 for m in metrics if m.get('claimed_pass_without_passing_run') and m.get('edited'))} | "
                     f"{sum(1 for m in metrics if m.get('zero_collected_seen'))} | "
                     f"{sum((r.get('eval_cost_usd') or 0) for r in group):.2f} |")
    return "\n".join(lines)


def diagnostics(runs):
    groups = defaultdict(list)
    for run in runs:
        for name, passed in (run.get("diagnostics") or {}).items():
            groups[(run["case"], name, run["arm"])].append(passed)
    lines = [f"- `{case}` {name}, {arm}: {sum(values)}/{len(values)}" for (case, name, arm), values in sorted(groups.items())]
    return "\n".join(lines) or "None."


def failures(runs):
    lines = []
    for run in sorted(runs, key=lambda r: (r["case"], r["arm"], r["run"])):
        failed = (run.get("hidden") or {}).get("failed") or []
        if failed:
            lines.append(f"- `{run['case']}` {run['arm']} run {run['run']}: {', '.join(failed)}")
    return "\n".join(lines) or "None."


def blind_packet(runs, out: Path, seed: int):
    """Anonymized diffs for human review. The key is a separate file: do not open it before scoring."""
    out.mkdir(parents=True)
    rng = random.Random(seed)
    key = {}
    shuffled = [run for run in runs if run.get("metrics")]
    rng.shuffle(shuffled)
    for number, run in enumerate(shuffled, 1):
        name = f"{run['case']}-{number:03d}"
        source = Path(run["source"]) / run["case"] / f"{run['raw_arm']}-{run['run']}"
        text = (source / "diff.patch").read_text() if (source / "diff.patch").exists() else ""
        (out / f"{name}.diff").write_text(text)
        (out / f"{name}.report.txt").write_text((source / "final_message.txt").read_text() if (source / "final_message.txt").exists() else "")
        key[name] = {"arm": run["arm"], "run": run["run"]}
    (out / "KEY-do-not-open-until-scored.json").write_text(json.dumps(key, indent=2))


def trigger_report(path: Path) -> str:
    """Trigger accuracy from a trigger-suite run. Graders are the source of truth here, not hidden checks."""
    document = json.loads(path.read_text())
    groups = defaultdict(list)
    lines = ["| Prompt | Kind | Split | Correct |", "|---|---|---|---:|"]
    for case in sorted(document["cases"], key=lambda c: c["name"]):
        name = case["name"]
        tags = (Path(__file__).parent / "cases" / "triggers" / name / "prompt.md").read_text().split("---")[1]
        kind = "positive" if name.startswith("pos-") else "negative" if name.startswith("neg-") else "read-only"
        split = "train" if "train" in tags else "test" if "test" in tags else "-"
        runs = case["arms"]["with"]
        correct = [all(g["passed"] for g in run["graders"]) for run in runs]
        groups[kind].extend(correct)
        groups[f"{kind}/{split}"].extend(correct)
        lines.append(f"| {name} | {kind} | {split} | {sum(correct)}/{len(correct)} |")
    lines += ["", "| Group | Correct |", "|---|---:|"]
    lines += [f"| {group} | {sum(values)}/{len(values)} |" for group, values in sorted(groups.items())]
    return "\n".join(lines) + f"\n\nCost: ${document['costUsd']:.2f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triggers", type=Path, help="aggregate-result.json from a trigger-suite run")
    parser.add_argument("--label", action="append", default=[], help="label=path/to/graded.json")
    parser.add_argument("--blind-out", type=Path)
    parser.add_argument("--seed", type=int, default=20261105)
    args = parser.parse_args()
    if args.triggers:
        print(trigger_report(args.triggers))
        return
    labels = [tuple(item.split("=", 1)) for item in args.label]
    runs = []
    for label, path in labels:
        for record in json.loads(Path(path).read_text()):
            record["raw_arm"] = record.get("arm")
            record["arm"] = label if record.get("arm") == "with" else record.get("arm")
            if record["arm"] == "without":
                record["arm"] = "no skill"
            record["source"] = str(Path(path).parent)
            runs.append(record)
    print("## Per case\n\n" + table(runs) + "\n\n## Totals\n\n" + totals(runs) + "\n\n## Diagnostic graders (not acceptance)\n\n" + diagnostics(runs) + "\n\n## Hidden check failures\n\n" + failures(runs))
    if args.blind_out:
        blind_packet(runs, args.blind_out, args.seed)
        print(f"\nBlind packet written to {args.blind_out}")


if __name__ == "__main__":
    main()
