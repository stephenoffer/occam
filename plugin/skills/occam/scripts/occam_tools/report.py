"""Rendering findings for an agent, a person, or CI. Output is bounded, because context is the scarce resource."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from . import VERSION
from .catalog import BY_ID, CATEGORIES, RULES, SEVERITIES


def location(finding: dict) -> str:
    if "cell" in finding:
        return f"{finding['path']}#cell{finding['cell']}:{finding['line']}"
    return f"{finding['path']}:{finding['line']}"


def _summary_table(findings: list[dict]) -> list[str]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for finding in findings:
        counts[finding["category"]][finding["severity"]] += 1
    lines = [f"  {'category':<20}{'crit':>5}{'high':>5}{'med':>5}{'low':>5}"]
    ordered = sorted(counts, key=lambda c: (-counts[c]["critical"], -counts[c]["high"], -counts[c]["medium"], CATEGORIES.index(c)))
    for category in ordered:
        row = counts[category]
        lines.append(f"  {category:<20}{row['critical'] or '.':>5}{row['high'] or '.':>5}{row['medium'] or '.':>5}{row['low'] or '.':>5}")
    return lines


def _hotspots(findings: list[dict], limit: int = 10) -> list[str]:
    scores: Counter = Counter()
    counts: Counter = Counter()
    for finding in findings:
        scores[finding["path"]] += finding["score"]
        counts[finding["path"]] += 1
    return [f"  {counts[path]:>4} findings  {path}" for path, _ in scores.most_common(limit)]


def render_text(findings: list[dict], hidden: int, stats: dict, top: int, saved_to: str | None = None) -> str:
    languages = ", ".join(f"{name} {count}" for name, count in sorted(stats["languages"].items(), key=lambda kv: -kv[1])) or "none"
    lines = [f"occam scan {VERSION}: {stats['analyzed']} of {stats['files']} files, {stats['lines']:,} lines, {stats['seconds']}s. {languages}.", *partial_note(stats)]
    if not findings:
        lines.append("No findings at this confidence. That isn't proof of quality: see the rules with `occam rules`, and read the risky paths yourself.")
    else:
        lines.append(f"{len(findings)} findings ({hidden} more below the confidence cut). These are leads: confirm each before calling it a defect.")
        lines += ["", *_summary_table(findings), "", "Files with the most weight:", *_hotspots(findings), "", f"Top {min(top, len(findings))}:"]
        for finding in findings[:top]:
            lines.append(f"  [{finding['severity'][:4].upper()}/{finding['confidence'][:3]}/{finding['tier']}] {finding['rule']}  {location(finding)}")
            lines.append(f"      {finding['message']}")
        if len(findings) > top:
            lines.append(f"  ... and {len(findings) - top} more.")
    gaps = []
    if stats.get("parse_errors"):
        gaps.append(f"{len(stats['parse_errors'])} Python files didn't parse on this interpreter, so only text rules ran on them: "
                    + ", ".join(path for path, _ in stats["parse_errors"][:5]))
    if stats.get("not_parsed_languages"):
        gaps.append("No parser here for " + ", ".join(stats["not_parsed_languages"]) + ", so those get text and brace-level rules only. `occam tools` lists better analyzers.")
    gaps += exemptions(stats) + isolated_note(stats)
    if gaps:
        lines += ["", "Limits of this scan:", *[f"  - {gap}" for gap in gaps]]
    lines += ["", "Tier: A mechanical, B fix with a check, C ask first."]
    if saved_to:
        lines.append(f"Full results: {saved_to}")
    return "\n".join(lines)


def isolated_note(stats: dict) -> list[str]:
    if not stats.get("isolated"):
        return []
    return ["Scanned in isolation, so the rules that need the rest of the repository didn't run: dead code, clones, import cycles, phantom local imports, untested modules."]


def left_unread(stats: dict) -> bool:
    """Were files in scope left unread? What wasn't read can't be called clean, while a scope read in full can, and says what else it couldn't see."""
    return bool((stats.get("partial") or {}).get("unread_in_scope"))


def partial_note(stats: dict) -> list[str]:
    """Comes first, because a clean result from part of a repository reads like a clean repository."""
    partial = stats.get("partial")
    if not partial:
        return []
    skipped = ("Rules needing the rest of the repository didn't run: unused and orphaned code, duplicates across files, imports of things that don't exist, dependency use, and what a removal breaks or orphans elsewhere. "
               "A lead here can also be explained by code that wasn't read, such as a re-export or a subclass.")
    if partial["reason"] == "scope":
        return [f"PARTIAL: this repository has {partial['repository_files']:,} files, too many to read for a scoped command, so only the {partial['read']:,} in scope were. {skipped} "
                "`--max-seconds 0` reads everything, which takes minutes and gigabytes, so run it in the background."]
    saved = "What was read is saved, so running this again gets further. " if partial.get("saved") else ""
    if partial["read"] == partial["wanted"]:
        return [f"PARTIAL: read all {partial['read']:,} files, but too near the {partial['seconds']}s limit to run the rest. {skipped} {saved}`--max-seconds 0` removes the limit, so run that in the background."]
    return [f"PARTIAL: reached the {partial['seconds']}s limit, having read {partial['read']:,} of {partial['wanted']:,} files. Files not reached have no findings here, which says nothing about them. {skipped} "
            f"{saved}On a repository this size a folder is what finishes, so name one, and `--max-seconds 0` removes the limit, so run that in the background."]


def exemptions(stats: dict) -> list[str]:
    """What a repository or its size kept out of this scan. It can't stay silent, because a repository can write these."""
    notes = []
    if stats.get("generated"):
        notes.append(f"{len(stats['generated'])} files marked generated or minified were skipped: " + ", ".join(stats["generated"][:5]))
    if stats.get("unscanned"):
        notes.append(f"{len(stats['unscanned'])} files couldn't be read (too large, binary or a symlink): " + ", ".join(stats["unscanned"][:5]))
    if stats.get("config_ignored") or stats.get("config_disabled"):
        notes.append(f".occam.json, which the repository controls, ignores {stats.get('config_ignored') or 'nothing'} and disables {stats.get('config_disabled') or 'nothing'}.")
    if stats.get("suppressed_inline"):
        notes.append(f"{stats['suppressed_inline']} findings were silenced by `occam: ignore` comments.")
    return notes


def render_json(findings: list[dict], stats: dict) -> str:
    return json.dumps({"version": VERSION, "stats": stats, "findings": findings}, indent=2)


_SARIF_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}


def render_sarif(findings: list[dict]) -> str:
    used = sorted({finding["rule"] for finding in findings})
    rules = [{"id": rule, "name": rule, "shortDescription": {"text": BY_ID[rule].title}, "help": {"text": BY_ID[rule].fix},
              "properties": {"category": BY_ID[rule].category, "layer": BY_ID[rule].layer}} for rule in used]
    results = []
    for finding in findings:
        results.append({
            "ruleId": finding["rule"], "level": _SARIF_LEVEL[finding["severity"]], "message": {"text": finding["message"]},
            "partialFingerprints": {"occam/v1": finding["id"]},
            "properties": {"confidence": finding["confidence"], "tier": finding["tier"]},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": finding["path"]}, "region": {"startLine": max(1, finding["line"])}}}],
        })
    return json.dumps({"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
                       "runs": [{"tool": {"driver": {"name": "occam", "version": VERSION, "rules": rules}}, "results": results}]}, indent=2)


def render_markdown(findings: list[dict], stats: dict) -> str:
    """A report a person can act on. Only things the tool knows go in. The agent adds what it read and judged."""
    lines = ["# Audit", "", f"Scanned {stats['analyzed']} of {stats['files']} files and {stats['lines']:,} lines with occam {VERSION}.",
             *partial_note(stats), "Findings here are leads.", ""]
    for severity in SEVERITIES:
        group = [f for f in findings if f["severity"] == severity]
        if not group:
            continue
        lines += [f"## {severity.capitalize()} ({len(group)})", ""]
        for finding in group[:50]:
            lines.append(f"- `{location(finding)}` **{finding['rule']}** ({finding['confidence']} confidence, tier {finding['tier']}): {finding['message']} *Fix:* {finding['fix']}")
        if len(group) > 50:
            lines.append(f"- ... and {len(group) - 50} more.")
        lines.append("")
    if stats.get("parse_errors") or stats.get("not_parsed_languages"):
        lines += ["## Not fully checked", ""]
        lines += [f"- `{path}` didn't parse on this interpreter." for path, _ in stats.get("parse_errors", [])[:20]]
        lines += [f"- {language}: text and brace-level rules only." for language in stats.get("not_parsed_languages", [])]
        lines.append("")
    return "\n".join(lines)


def render_rules(rule_id: str | None = None) -> str:
    if rule_id:
        rule = BY_ID.get(rule_id)
        if not rule:
            return f"No rule named {rule_id}."
        return (f"{rule.id} ({rule.category}, layer {rule.layer})\n  {rule.title}\n  severity {rule.severity}, confidence {rule.confidence}, tier {rule.tier}\n  fix: {rule.fix}")
    lines = []
    for name in CATEGORIES:
        lines.append(f"{name}:")
        lines += [f"  {rule.id:<30}{rule.severity:<9}{rule.confidence:<7}{rule.tier}  {rule.title}" for rule in RULES if rule.category == name]
    return "\n".join(lines)
