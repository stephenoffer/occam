"""Remembering findings between scans: a baseline for large repositories, and a ledger for triage and repair.

Everything lives in one sqlite file outside the repository (see files.state_dir), so concurrent agents can share it, nothing dirties the tree,
and a repository can't plant commands or verdicts here.
"""

from __future__ import annotations

import fnmatch
import json
import time
from pathlib import Path

from . import report, scan as scanner
from .catalog import SEVERITIES
from .workflow import claim_holder, database

_RESOLVED = ("fixed", "false-positive", "accepted")
_IN_PROGRESS_SECONDS = 2 * 3600


def _scan(root: Path, paths=None, changed_only=False, base=None) -> scanner.ScanResult:
    return scanner.run_scan(root, paths, changed_only=changed_only, base=base)


def write_baseline(root: Path, out: str | None = None) -> str:
    result = _scan(root)
    identities = sorted({f["id"] for f in result.findings})
    if out:
        Path(out).write_text(json.dumps(identities, indent=0) + "\n")
        return f"Baseline of {len(identities)} findings written to {out}. Commit it, and use `occam scan --baseline {out}` in CI."
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM baseline")
        db.executemany("INSERT OR IGNORE INTO baseline VALUES (?)", [(identity,) for identity in identities])
        db.execute("COMMIT")
    return f"Baseline holds {len(identities)} findings. `occam scan --new-only` now shows only what is added after this point. It lives on this machine, so for CI use --out."


def show_baseline(root: Path) -> str:
    with database(root) as db:
        count = db.execute("SELECT COUNT(*) FROM baseline").fetchone()[0]
    return f"Baseline holds {count} findings." if count else "No baseline yet. `occam baseline write` creates one."


def new_since_baseline(root: Path, findings: list[dict], baseline_file: str | None = None) -> tuple[list[dict], str | None]:
    """Findings the baseline doesn't know, and a warning if there's no baseline to compare with."""
    if baseline_file:
        try:
            known = set(json.loads(Path(baseline_file).read_text()))
        except (OSError, ValueError) as error:
            return findings, f"Couldn't read {baseline_file} ({error}), so everything counts as new."
    else:
        with database(root) as db:
            known = {row[0] for row in db.execute("SELECT id FROM baseline")}
        if not known:
            return findings, "No baseline on this machine, so everything counts as new. `occam baseline write` creates one."
    return [f for f in findings if f["id"] not in known], None


def sync(root: Path, paths=None, changed_only=False, base=None, min_confidence="medium") -> str:
    """Add new findings, and close tracked ones only with evidence that they're gone.

    A finding is gone only if a full scan really read its file and found nothing, whatever confidence was being listed.
    A file that didn't parse, or that couldn't be read, proves nothing.
    """
    result = _scan(root, paths, changed_only, base)
    everything = {f["id"]: f for f in result.findings}
    current = {f["id"]: f for f in scanner.filter_findings(result.findings, min_confidence)}
    covered_all = not paths and not changed_only and not base
    unknown = {path for path, _ in result.stats["parse_errors"]} | set(result.stats["unscanned"]) | set(result.stats["generated"])
    disabled = set(result.stats.get("config_disabled", []))
    ignored = result.stats.get("config_ignored", [])

    def proves_gone(finding: dict) -> bool:
        """Only a real read of the file, with the rule running. A cross-file finding depends on every file having been read."""
        if finding["path"] in unknown or finding["rule"] in disabled or any(fnmatch.fnmatch(finding["path"], g) or finding["path"].startswith(g.rstrip("/") + "/") for g in ignored):
            return False
        return bool(finding.get("evidence")) or not unknown

    now = time.time()
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = {row[0]: (row[1], json.loads(row[2])) for row in db.execute("SELECT id, status, data FROM ledger")}
        new = [(identifier, json.dumps(finding), now) for identifier, finding in current.items() if identifier not in existing]
        seen_again = []
        for identifier, finding in everything.items():
            if identifier in existing:
                note = existing[identifier][1].get("note")
                seen_again.append((json.dumps({**finding, **({"note": note} if note else {})}), now, identifier))
        reopened = [(identifier,) for identifier in everything if identifier in existing and existing[identifier][0] == "fixed"]
        gone = [(now, identifier) for identifier, (status, finding) in existing.items()
                if covered_all and identifier not in everything and status not in _RESOLVED and proves_gone(finding)]
        db.executemany("INSERT INTO ledger VALUES (?, ?, 'open', NULL, ?)", new)
        db.executemany("UPDATE ledger SET data = ?, updated = ? WHERE id = ?", seen_again)
        db.executemany("UPDATE ledger SET status = 'open' WHERE id = ?", reopened)
        db.executemany("UPDATE ledger SET status = 'fixed', updated = ? WHERE id = ?", gone)
        db.execute("INSERT OR REPLACE INTO kv VALUES ('stats', ?)", (json.dumps(result.stats),))
        db.execute("COMMIT")
    added, closed = len(new), len(gone)
    return f"Ledger: {added} new, {closed} no longer present, {len(current)} current from {result.stats['files']} files."


def _rows(root: Path) -> list[tuple[dict, str, str | None, str]]:
    with database(root) as db:
        return [(json.loads(data), status, owner, note or "") for data, status, owner, note in
                db.execute("SELECT data, status, owner, json_extract(data, '$.note') FROM ledger")]


def _rank(row: tuple) -> tuple:
    finding = row[0]
    return (-finding.get("score", 0), finding["path"], finding["line"])


def listing(root: Path, status=None, tier=None, category=None, limit=40) -> str:
    rows = [r for r in _rows(root) if (status is None or r[1] == status) and (tier is None or r[0]["tier"] == tier) and (category is None or r[0]["category"] == category)]
    if not rows:
        return "Nothing matches."
    rows.sort(key=_rank)
    lines = [f"{len(rows)} findings:"]
    for finding, state, owner, _ in rows[:limit]:
        lines.append(f"  {finding['id']}  {state:<14} {finding['severity'][:4]}/{finding['tier']}  {finding['rule']}  {report.location(finding)}{'  @' + owner if owner else ''}")
    if len(rows) > limit:
        lines.append(f"  ... and {len(rows) - limit} more.")
    return "\n".join(lines)


def set_status(root: Path, identifiers: list[str], status: str | None, note: str | None, owner: str | None) -> str:
    if not identifiers:
        return "Give --ids."
    changed = 0
    with database(root) as db:
        for identifier in identifiers:
            row = db.execute("SELECT data, status FROM ledger WHERE id = ?", (identifier,)).fetchone()  # occam: ignore[query-in-loop] a handful of ids
            if not row:
                continue
            data = json.loads(row[0])
            if note:
                data["note"] = note
            db.execute("UPDATE ledger SET data = ?, status = ?, owner = COALESCE(?, owner), updated = ? WHERE id = ?",  # occam: ignore[query-in-loop] a handful of ids
                       (json.dumps(data), status or row[1], owner, time.time(), identifier))
            changed += 1
    return f"Updated {changed} of {len(identifiers)}."


def next_batch(root: Path, owner=None, size=5, tier=None) -> str:
    """The next findings to work on, from one file, skipping files someone else has claimed. Claims them atomically."""
    now = time.time()
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        claimed = {path: who for path, who, expires in db.execute("SELECT path, owner, expires FROM claims") if expires > now and who != owner}
        # Work in progress is abandoned after a while, so an agent that died can't hold a file forever.
        stale = now - _IN_PROGRESS_SECONDS
        db.execute("UPDATE ledger SET status = 'open', owner = NULL WHERE status = 'in-progress' AND updated < ?", (stale,))
        taken = {json.loads(data)["path"] for data, state, who in db.execute("SELECT data, status, owner FROM ledger") if state == "in-progress" and who != owner}
        rows = [(json.loads(data), state) for data, state in db.execute("SELECT data, status FROM ledger WHERE status IN ('confirmed', 'open')")]
        rows = [r for r in rows if not claim_holder(claimed, r[0]["path"]) and r[0]["path"] not in taken and (tier is None or r[0]["tier"] == tier)]
        if not rows:
            db.execute("COMMIT")
            return "Nothing left to take: everything open is resolved, needs a decision, or is held by another agent."
        rows.sort(key=lambda r: (r[1] != "confirmed", -r[0].get("score", 0)))
        path = rows[0][0]["path"]
        batch = [r for r in rows if r[0]["path"] == path][:size]
        for finding, _ in batch:
            db.execute("UPDATE ledger SET status = 'in-progress', owner = ?, updated = ? WHERE id = ?", (owner, now, finding["id"]))  # occam: ignore[query-in-loop] one small batch
        db.execute("COMMIT")
    lines = [f"Batch for {owner or 'this agent'}, all in {path}:"]
    for finding, _ in batch:
        lines.append(f"  {finding['id']}  [{finding['severity']}/{finding['tier']}] {finding['rule']} line {finding['line']}: {finding['message']}")
        lines.append(f"      fix: {finding['fix']}")
    lines.append("Confirm each first. Then `occam ledger set --ids ... --status fixed` or false-positive or needs-decision, with a --note.")
    return "\n".join(lines)


def decisions(root: Path) -> str:
    """Everything waiting on a person, as material for one concrete question."""
    rows = [r for r in _rows(root) if r[1] == "needs-decision" or (r[1] == "confirmed" and r[0]["tier"] == "C")]
    if not rows:
        return "No decisions pending."
    rows.sort(key=_rank)
    lines = [f"{len(rows)} decisions need a person. Group related ones, and ask with the action, reason, consequences and your recommendation:"]
    for finding, _, _, note in rows[:30]:
        lines.append(f"  {finding['id']}  {report.location(finding)}  {finding['rule']}: {finding['message']}")
        lines.append(f"      proposed fix: {finding['fix']}" + (f"  note: {note}" if note else ""))
    return "\n".join(lines)


def markdown_report(root: Path, out: str | None, title: str) -> str:
    rows = _rows(root)
    with database(root) as db:
        stored = db.execute("SELECT value FROM kv WHERE key = 'stats'").fetchone()
    if not rows or not stored:
        return "The ledger is empty. Run `occam ledger sync` first."
    stats = json.loads(stored[0])
    state = {finding["id"]: {"status": status, "note": note} for finding, status, _, note in rows}
    findings = [finding for finding, _, _, _ in rows]
    findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), -f.get("score", 0)))
    text = report.render_markdown(findings, stats, state, title)
    if out:
        Path(out).write_text(text)
        return f"Wrote {out}."
    return text
