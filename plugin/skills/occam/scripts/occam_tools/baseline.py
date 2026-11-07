"""A ratchet for large repositories: accept today's findings, so only new ones count.

It lives in one sqlite file outside the repository (see files.state_dir), so nothing dirties the tree and a repository can't plant verdicts here.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import scan as scanner
from .workflow import database


def write_baseline(root: Path, out: str | None = None) -> str:
    result = scanner.run_scan(root)
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
        except (OSError, ValueError, TypeError) as error:
            return findings, f"Couldn't read {baseline_file} ({error}), so everything counts as new."
    else:
        with database(root) as db:
            known = {row[0] for row in db.execute("SELECT id FROM baseline")}
        if not known:
            return findings, "No baseline on this machine, so everything counts as new. `occam baseline write` creates one."
    return [f for f in findings if f["id"] not in known], None
