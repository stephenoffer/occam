#!/usr/bin/env python3
"""Where an eval's money went, read from saved traces. Spends nothing.

    cost_report.py LABEL [LABEL ...] [--results DIR]

Each run's last `result` row holds whole-run tokens per model in `modelUsage`. Its `usage` covers only the main
conversation's last segment, so a run the Stop hook sent back has one `result` row per segment and they must be
summed. Whole-run minus main is what subagents used. Traces undercount subagents and output tokens, so neither is
taken from the assistant rows.

The 5-minute columns reprice main-conversation cache writes, and treat any gap over 5 minutes between two main
messages as a miss that writes the whole context again. These are estimates of a bill, not of behavior.
"""

import argparse
import gzip
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Dollars per million tokens: input, 5-minute cache write, 1-hour cache write, cache read, output.
# Fitted to saved runs, where they reproduce the CLI's cost estimate exactly. They are list prices, not plan usage.
PRICES = {
    "claude-opus-5-5": (4, 5, 8, 0.2, 20),
    "claude-sonnet-5-5": (2, 2.5, 4, 0.1, 10),
    "claude-haiku-5-5": (0.1, 0.125, 0.2, 0.01, 0.5),
}
CACHE_LIFETIME_S = 300


def read_rows(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def seconds(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def gap_misses(rows):
    """Tokens that a 5-minute cache would have had to write again, and how many gaps caused that."""
    first_seen = {}
    for row in rows:
        message = row.get("message")
        if row.get("type") != "assistant" or row.get("parent_tool_use_id") or not isinstance(message, dict):
            continue
        if message.get("usage") and row.get("timestamp") and message.get("id") not in first_seen:
            first_seen[message.get("id")] = (seconds(row["timestamp"]), message["usage"].get("cache_read_input_tokens", 0) or 0)
    ordered = sorted(first_seen.values())
    misses = [read for (before, _), (now, read) in zip(ordered, ordered[1:]) if now - before > CACHE_LIFETIME_S]
    return sum(misses), len(misses)


def run_cost(rows):
    """Cost split of one run, or None if it left no result row, as a run stopped at the time limit does."""
    rows = list(rows)
    results = [row for row in rows if row.get("type") == "result" and row.get("modelUsage")]
    if not results:
        return None
    usage = defaultdict(int)
    for result in results:
        for key in ("input_tokens", "cache_read_input_tokens", "output_tokens"):
            usage[key] += result["usage"].get(key, 0) or 0
        creation = result["usage"].get("cache_creation") or {}
        usage["w5"] += creation.get("ephemeral_5m_input_tokens", 0) or 0
        usage["w1"] += creation.get("ephemeral_1h_input_tokens", 0) or 0
    models = results[-1]["modelUsage"]
    model = _main_model(rows, models)
    total = sum(entry["costUSD"] for entry in models.values())
    if model not in PRICES:
        return {"model": model, "total": total, "unpriced": True, "segments": len(results)}
    price = PRICES[model]
    write = (usage["w5"] * price[1] + usage["w1"] * price[2]) / 1e6
    read = usage["cache_read_input_tokens"] * price[3] / 1e6
    output = usage["output_tokens"] * price[4] / 1e6
    main_input = usage["input_tokens"] * price[0] / 1e6
    missed_tokens, missed_gaps = gap_misses(rows)
    cheaper = usage["w1"] * (price[2] - price[1]) / 1e6
    rewrite = missed_tokens * (price[1] - price[3]) / 1e6
    return {"model": model, "total": total, "segments": len(results), "write": write, "read": read, "output": output,
            "subagents": max(0.0, total - write - read - output - main_input), "five_min": total - cheaper,
            "five_min_gaps": total - cheaper + rewrite, "gaps_over": missed_gaps, "turns": results[-1].get("num_turns") or 0,
            "w1": usage["w1"], "w5": usage["w5"]}


def _main_model(rows, models):
    """The model the main conversation ran on, as the run's init row or first top-level message says. A costlier subagent model
    would otherwise price the main conversation's tokens, and the split between them would be wrong. The costliest is a last resort."""
    for row in rows:
        named = row.get("model") if row.get("type") == "system" else (row.get("message") or {}).get("model") if row.get("type") == "assistant" and not row.get("parent_tool_use_id") else None
        if named in models:
            return named
    return max(models, key=lambda name: models[name]["costUSD"])


def collect(folder):
    """{case: {arm: [run cost]}} for an eval's saved traces, in either layout."""
    runs = defaultdict(lambda: defaultdict(list))
    found = [(path.parts[-3], path.parts[-2], path) for path in folder.glob("graded/*/*/trace.jsonl")]
    found += [(folder.name, path.name.split(".")[0], path) for path in folder.glob("traces/*.jsonl*")]
    for case, arm_run, path in found:
        cost = run_cost(read_rows(path))
        if cost:
            runs[case][arm_run.rsplit("-", 1)[0]].append(cost)
    return runs


def mean(costs, key):
    return statistics.mean(cost.get(key, 0) for cost in costs) if costs else 0.0


def overhead_line(cases, base, extra):
    line = f"Paired by case, {cases} case{'s' if cases != 1 else ''}: {extra['total'] / base:+.0%} over no skill."
    if abs(extra["total"]) < 0.05 * base:  # Parts of a near-zero total can be any size, so their shares mean nothing.
        return line + " Too close to zero to split by part."
    shares = (f"{key} {round(100 * extra[key] / extra['total']) + 0}%" for key in ("write", "read", "output", "subagents"))
    return line + f" Share of the {'extra' if extra['total'] > 0 else 'saving'}: " + ", ".join(shares)


def report(folder):
    runs = collect(folder)
    lines = [f"\n{folder.name}",
             "| Arm | Runs | $/run | Main writes | Main reads | Main output | Subagents | Turns | At 5 min | At 5 min with misses | Gaps over 5 min/run |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in ("without", "with"):
        costs = [cost for case in runs.values() for cost in case.get(arm, []) if not cost.get("unpriced")]
        if costs:
            lines.append(f"| {arm} | {len(costs)} | " + " | ".join(f"{mean(costs, key):.3f}" for key in ("total", "write", "read", "output", "subagents"))
                         + f" | {mean(costs, 'turns'):.1f} | {mean(costs, 'five_min'):.3f} | {mean(costs, 'five_min_gaps'):.3f} | {mean(costs, 'gaps_over'):.2f} |")
    # An unpriced run has no parts, and averaging it in would count them as zero, so paired means use priced runs only.
    priced = [{arm: [cost for cost in costs if not cost.get("unpriced")] for arm, costs in case.items()} for case in runs.values()]
    paired = [case for case in priced if case.get("with") and case.get("without")]
    if paired:
        base = sum(mean(case["without"], "total") for case in paired)
        extra = {key: sum(mean(case["with"], key) - mean(case["without"], key) for case in paired) for key in ("total", "write", "read", "output", "subagents")}
        lines.append(overhead_line(len(paired), base, extra))
        five = sum(mean(case["without"], "five_min_gaps") for case in paired)
        five_extra = sum(mean(case["with"], "five_min_gaps") - mean(case["without"], "five_min_gaps") for case in paired)
        lines.append(f"At a 5-minute cache: {five_extra / five:+.0%} over no skill.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", nargs="+")
    parser.add_argument("--results", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()
    for label in args.labels:
        print(report(args.results / label))


if __name__ == "__main__":
    main()
