"""A ratchet for large repositories: accept today's findings, so only new ones count.

It lives in one sqlite file outside the repository (see files.state_dir), so nothing dirties the tree and a repository can't plant verdicts here.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import VERSION, report, scan as scanner
from .workflow import database


def _provenance(stats: dict) -> dict:
    """What a baseline was made with and from, so a later comparison can say when it can't be taken at its word."""
    return {"occam": VERSION, "ids": scanner.IDENTITY_VERSION, "python": f"{sys.version_info.major}.{sys.version_info.minor}", "written": int(time.time()),
            "gaps": [*report.incomplete(stats), *report.exemptions(stats)]}


def write_baseline(root: Path, out: str | None = None) -> str:
    result = scanner.run_scan(root)
    identities = sorted(set(scanner.ids_of(result.findings)))
    made = {**_provenance(result.stats), "findings": len(result.findings)}
    caveat = (" What it accepted was read with these limits, so they're accepted too: " + "; ".join(made["gaps"])) if made["gaps"] else ""
    if out:
        Path(out).write_text(json.dumps([_MADE_MARK + json.dumps(made), *identities], indent=0) + "\n")
        return f"Baseline of {len(result.findings)} findings written to {out}. Commit it, and use `occam scan --baseline {out}` in CI.{caveat}"
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM baseline")
        db.executemany("INSERT OR IGNORE INTO baseline VALUES (?)", [(identity,) for identity in identities])
        db.execute("INSERT OR REPLACE INTO kv VALUES ('baseline-made', ?)", (json.dumps(made),))
        db.execute("COMMIT")
    return f"Baseline holds {len(result.findings)} findings. `occam scan --new-only` now shows only what is added after this point. It lives on this machine, so for CI use --out.{caveat}"


def show_baseline(root: Path) -> str:
    with database(root) as db:
        count = db.execute("SELECT COUNT(*) FROM baseline").fetchone()[0]
        row = db.execute("SELECT value FROM kv WHERE key = 'baseline-made'").fetchone()
    count = json.loads(row[0]).get("findings", count) if count and row else count  # a finding can be kept under two ids (scan.ids_of)
    return f"Baseline holds {count} findings." if count else "No baseline yet. `occam baseline write` creates one."


def _mismatch(made: dict | None, where: str) -> str | None:
    if not made or made.get("ids") != scanner.IDENTITY_VERSION:
        return (f"{where} was written by an occam that made finding ids another way, so some findings it accepted may show as new here. "
                "Writing the baseline again with this version fixes that.")
    here = f"{sys.version_info.major}.{sys.version_info.minor}"
    if made.get("python") != here:
        return f"{where} was written on Python {made.get('python')} and this is {here}, and what parses and what the standard library has differ, so some findings may differ."
    return None


# A baseline file stays the list of ids an older occam reads. How it was made rides as its first entry, which an older version takes
# for one more id it never sees, so a file written here still works in a CI that pins an older occam.
_MADE_MARK = "occam-baseline-made "


def _read_file(baseline_file: str) -> tuple[set, dict | None]:
    """The ids a baseline file accepts, and how it was made, or None for a baseline from before it recorded that."""
    saved = json.loads(Path(baseline_file).read_text())
    if not isinstance(saved, list):
        raise ValueError("it isn't a list of finding ids")  # read as no baseline, so everything counts as new and nothing is let through
    entries = [entry for entry in saved if isinstance(entry, str)]
    made = next((json.loads(entry[len(_MADE_MARK):]) for entry in entries if entry.startswith(_MADE_MARK)), None)
    return {entry for entry in entries if not entry.startswith(_MADE_MARK)}, made if isinstance(made, dict) else None


def new_since_baseline(root: Path, findings: list[dict], baseline_file: str | None = None) -> tuple[list[dict], str | None]:
    """Findings the baseline doesn't know, and a warning if there's no baseline to compare with or it was made differently."""
    if baseline_file:
        try:
            known, made = _read_file(baseline_file)
        except (OSError, ValueError, TypeError) as error:
            return findings, f"Couldn't read {baseline_file} ({error}), so everything counts as new."
        where = baseline_file
    else:
        with database(root) as db:
            known = {row[0] for row in db.execute("SELECT id FROM baseline")}
            row = db.execute("SELECT value FROM kv WHERE key = 'baseline-made'").fetchone()
        if not known:
            return findings, "No baseline on this machine, so everything counts as new. `occam baseline write` creates one."
        made, where = (json.loads(row[0]) if row else None), "The baseline on this machine"
    return [f for f in findings if f["id"] not in known], _mismatch(made, where)
