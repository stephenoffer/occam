"""Rendering findings for an agent, a person, or CI. Output is bounded, because context is the scarce resource."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from urllib.parse import quote

from . import VERSION
from .catalog import BY_ID, CATEGORIES, RULES, SEVERITIES


def location(finding: dict) -> str:
    if "cell" in finding:
        return f"{finding['path']}#cell{finding['cell']}:{finding['line']}"
    return f"{finding['path']}:{finding['line']}"


TIER_WORDS = {"A": "tier A: a mechanical fix", "B": "tier B: fix with a check", "C": "tier C: ask first"}


def headline(finding: dict) -> str:
    """One finding as a person reads it: `MEDIUM  leap.py:38  swallowed-exception (high confidence, tier B: fix with a check)`."""
    how = ", ".join(part for part in (f"{finding['confidence']} confidence" if finding.get("confidence") else "", TIER_WORDS.get(finding.get("tier"), "")) if part)
    return f"{finding['severity'].upper():<8}  {location(finding)}  {finding['rule']}" + (f" ({how})" if how else "")


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


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x80-\x9f]")  # what a terminal acts on: a path or a message from a repository can hold these


def _shown(text: str) -> str:
    return _CONTROL.sub(lambda match: f"\\x{ord(match.group(0)):02x}", text)


def render_text(findings: list[dict], hidden: int, stats: dict, top: int, saved_to: str | None = None) -> str:
    one_line = [{**finding, "path": finding["path"].replace("\n", "\\n"), "message": finding["message"].replace("\n", "\\n")} for finding in findings]  # a name can't forge a line
    return _shown(_render_text(one_line, hidden, stats, top, saved_to))


def _render_text(findings: list[dict], hidden: int, stats: dict, top: int, saved_to: str | None = None) -> str:
    languages = ", ".join(f"{name} {count}" for name, count in sorted(stats["languages"].items(), key=lambda kv: -kv[1])) or "none"
    lines = [f"occam scan {VERSION}: {stats['analyzed']} of {stats['files']} files, {stats['lines']:,} lines, {stats['seconds']}s. {languages}.", *partial_note(stats)]
    if not findings:
        lines.append("No findings at this confidence. That isn't proof of quality: see the rules with `occam rules`, and read the risky paths yourself.")
    else:
        lines.append(f"{len(findings)} findings ({hidden} more below the confidence cut). These are leads: confirm each before calling it a defect.")
        lines += ["", *_summary_table(findings), "", "Files with the most weight:", *_hotspots(findings), "", f"Top {min(top, len(findings))}:"]
        for finding in findings[:top]:
            lines.append(f"  {headline(finding)}")
            lines.append(f"      {finding['message']}")
        if len(findings) > top:
            lines.append(f"  ... and {len(findings) - top} more.")
    gaps = []
    if stats.get("parse_errors"):
        gaps.append(f"{len(stats['parse_errors'])} Python files didn't parse on this interpreter, so only text rules ran on them: "
                    + ", ".join(path for path, _ in stats["parse_errors"][:5]))
    if stats.get("not_parsed_languages"):
        gaps.append("No parser here for " + ", ".join(stats["not_parsed_languages"]) + ", so those get text and brace-level rules only. `occam tools` lists better analyzers.")
    gaps += [*stats.get("notes", []), *exemptions(stats), *isolated_note(stats)]  # notes: checks that couldn't run, such as the standard library probe
    if gaps:
        lines += ["", "Limits of this scan:", *[f"  - {gap}" for gap in gaps]]
    if saved_to:
        lines.append(f"Full results: {saved_to}")
    return "\n".join(lines)


def isolated_note(stats: dict) -> list[str]:
    if not stats.get("isolated"):
        return []
    return ["Scanned in isolation, so the rules that need the rest of the repository didn't run: dead code, clones, import cycles, phantom local imports, untested modules."]


def incomplete(stats: dict) -> list[str]:
    """Why a pass can't be vouched for: code in scope left unread or unreadable, or the repository-wide rules cut by a time limit. What
    wasn't read can't be called clean. A scoped command in a large repository is complete for its scope, and says what else it couldn't see."""
    partial = stats.get("partial") or {}
    gaps = [f"{partial['unread_in_scope']:,} files in scope weren't read before the time limit"] if partial.get("unread_in_scope") else []
    unreadable = stats.get("unread_code", [])  # a big lockfile or data file was never a promise, and a link is read where it points
    if unreadable:
        gaps.append(f"{len(unreadable)} code files were too large or too slow to read: " + ", ".join(unreadable[:5]))
    scoped = stats.get("files", 0) < (partial.get("repository_files") or 0)  # a scope read in full passes, and says what else it couldn't see
    if partial.get("reason") == "time" and not partial.get("unread_in_scope") and not scoped:
        gaps.append("the rules that need the whole repository didn't run before the time limit")
    return gaps


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
        notes.append(f"{len(stats['generated'])} files marked generated or minified were read only for secrets: " + ", ".join(stats["generated"][:5]))
    if stats.get("skipped_by_name"):
        notes.append(f"{stats['skipped_by_name']:,} files in vendored, build or generated folders (vendor/, dist/, build/, node_modules/ and the like) weren't read. Name one to read it.")
    if stats.get("unscanned"):
        notes.append(f"{len(stats['unscanned'])} files couldn't be read (too large, too slow to read, binary or a symlink): " + ", ".join(stats["unscanned"][:5]))
    if stats.get("config_ignored") or stats.get("config_disabled"):
        notes.append(f".occam.json, which the repository controls, ignores {stats.get('config_ignored') or 'nothing'} and disables {stats.get('config_disabled') or 'nothing'}.")
    if stats.get("suppressed_inline"):
        notes.append(f"{stats['suppressed_inline']} findings were silenced by `occam: ignore` comments.")
    return notes


def render_json(findings: list[dict], stats: dict) -> str:
    return json.dumps({"version": VERSION, "stats": stats, "findings": findings}, indent=2)


_SARIF_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}


def _sarif_location(finding: dict) -> dict:
    """A path as a URI, so a space, `#` or `%` in it can't change what it names. A notebook's line counts within its cell, not within the
    file's JSON, so it gets the cell and that line as properties instead of a region pointing at the wrong line."""
    artifact = {"artifactLocation": {"uri": quote(finding["path"], safe="/")}}
    if "cell" in finding:
        return {"physicalLocation": artifact, "properties": {"cell": finding["cell"], "lineInCell": finding["line"]}}
    return {"physicalLocation": {**artifact, "region": {"startLine": max(1, finding["line"])}}}


def render_sarif(findings: list[dict], stats: dict | None = None) -> str:
    used = sorted({finding["rule"] for finding in findings})
    rules = [{"id": rule, "name": rule, "shortDescription": {"text": BY_ID[rule].title}, "help": {"text": BY_ID[rule].fix},
              "properties": {"category": BY_ID[rule].category, "layer": BY_ID[rule].layer}} for rule in used]
    results = []
    for finding in findings:
        results.append({
            "ruleId": finding["rule"], "level": _SARIF_LEVEL[finding["severity"]], "message": {"text": finding["message"]},
            "partialFingerprints": {"occam/v1": finding["id"]},
            "properties": {"confidence": finding["confidence"], "tier": finding["tier"]},
            "locations": [_sarif_location(finding)],
        })
    # Whether the analysis finished goes in the file, since a code-scanning page shows "no results" the same either way.
    gaps = [*incomplete(stats), *partial_note(stats), *exemptions(stats)] if stats is not None else []
    invocation = {"executionSuccessful": not (stats is not None and incomplete(stats)),
                  "toolExecutionNotifications": [{"level": "warning", "message": {"text": gap}} for gap in gaps]}
    return json.dumps({"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
                       "runs": [{"tool": {"driver": {"name": "occam", "version": VERSION, "rules": rules}}, "invocations": [invocation], "results": results}]}, indent=2)


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
    limits = [*incomplete(stats), *exemptions(stats), *isolated_note(stats), *stats.get("notes", [])]
    if stats.get("parse_errors") or stats.get("not_parsed_languages") or limits:
        lines += ["## Not fully checked", ""]
        lines += [f"- `{path}` didn't parse on this interpreter." for path, _ in stats.get("parse_errors", [])[:20]]
        lines += [f"- {language}: text and brace-level rules only." for language in stats.get("not_parsed_languages", [])]
        lines += [f"- {limit}" for limit in limits]
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
