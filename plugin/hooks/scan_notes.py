"""Lets a hook ask the scanner about one file, and say only what this change introduced.

Shared by the Claude Code and Codex hooks. Everything here is best effort: a hook must never fail because of it.
"""

from __future__ import annotations

import os
import re
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "occam" / "scripts"))

MAX_BYTES = 300_000
MAX_SECONDS = 2
STOP_SECONDS = 5
MAX_LISTED = 5
MAX_FILES_AT_STOP = 8
AUDIT_FILES_AT_STOP = 40
# Worth interrupting for even at medium confidence, because they rarely appear by accident. The last three are the fake integrations
# developers complain of: each fired 0 times at medium confidence in 641 standard-library files, and 5 times in 4,947 installed-package
# files (2026-11-06). stub-raise isn't here: base classes raising NotImplementedError gave it 70 in the standard library.
ALWAYS_SERIOUS = {"truncation-marker", "fake-success", "hardcoded-secret", "stub-body", "failure-reported-as-success", "fallback-fake", "mock-in-production"}
# Those three are said once, as an edit introduces them, and never send the agent back at Stop, per DESIGN.md's no-new-send-backs.
# They are about code that ships, and test support often lives outside a test folder: Django's tests.py, testing.py, fixtures,
# pytest plugins, noxfile.py, and docs, scripts and examples. There they stay leads for `occam scan`, not interruptions.
FAKES = {"failure-reported-as-success", "fallback-fake", "mock-in-production"}
NOT_SHIPPED = re.compile(r"(^|/)(tests?|testing|spec|__tests__|fixtures)/|^(docs?|examples?|samples?|demos?|scripts?|benchmarks?|notebooks?)/"
                         r"|(^|/)(tests?|testing|fixtures|conftest|noxfile|fabfile|[^/]*pytest_plugin[^/]*|test_[^/]+)\.py$|\.(test|spec)\.[a-z]+$", re.I)


class _TooSlow(Exception):
    pass


def _scan(relative: str, text: str) -> list[dict]:
    """Bounded in time, because a hook runs on every edit and a file can be built to be slow to scan."""
    from occam_tools import scan

    def give_up(*_):
        raise _TooSlow

    if not hasattr(signal, "setitimer"):
        return scan.scan_text(relative, text)
    remaining, interval = signal.getitimer(signal.ITIMER_REAL)  # the hook's own limit, which this mustn't cancel
    started = time.monotonic()
    previous = signal.signal(signal.SIGALRM, give_up)
    signal.setitimer(signal.ITIMER_REAL, min(MAX_SECONDS, remaining) if remaining else MAX_SECONDS)
    try:
        return scan.scan_text(relative, text)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if remaining:
            signal.setitimer(signal.ITIMER_REAL, max(remaining - (time.monotonic() - started), 0.01), interval)


def _is_serious(finding: dict) -> bool:
    if finding["rule"] in FAKES and NOT_SHIPPED.search(finding.get("path", "")):
        return False
    if finding["rule"] in ALWAYS_SERIOUS and finding["confidence"] != "low":
        return True
    return finding["severity"] in ("critical", "high") and finding["confidence"] == "high"


def _read(path: Path) -> str | None:
    """A regular file small enough to scan in a hook. A FIFO or device named like code would wait forever, or read without end."""
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def identities(path: Path, relative: str) -> list[str] | None:
    """What the file already has, before an edit. None if it couldn't be scanned, since that isn't the same as having no findings."""
    if not path.exists():
        return []
    try:
        text = _read(path)
        return ids_of(_scan(relative, text)) if text is not None else None
    except (Exception, _TooSlow):  # occam: ignore[swallowed-exception] a broken scan must not take the hook down
        return None


def ids_of(findings: list[dict]) -> list[str]:
    """Every id the findings answer to, so one already there is known after a copy of it is added or removed (scan.ids_of)."""
    from occam_tools import scan

    return scan.ids_of(findings)


def within_budget(paths: list, most: int = MAX_FILES_AT_STOP, left: list | None = None) -> Iterator:
    """Iterate while time remains, so several large files can't push a hook past its limit. What it didn't reach goes in `left`."""
    started = time.monotonic()
    for index, path in enumerate(paths):
        if index >= most or time.monotonic() - started > STOP_SECONDS:
            if left is not None:
                left.extend(paths[index:])
            return
        yield path


def committed_identities(root: Path, relative: str) -> list[str] | None:
    """What the last commit's version has, when nothing recorded it before the edit. None without git or a prior version."""
    try:
        from occam_tools.files import run_git  # a repository's own config can name programs for plain git to run

        committed = run_git(root, "show", f"HEAD:./{relative}", timeout=5)
        return ids_of(_scan(relative, committed)) if committed is not None else None
    except Exception:  # occam: ignore[swallowed-exception] fails open, like identities
        return None


def introduced(path: Path, relative: str, known: list[str] | None, noting: bool = False) -> list[dict]:
    """Serious findings in the file now that weren't there before. Without a baseline nothing can be attributed to this change.
    `noting` is for the note after an edit, which also says the FAKES. At Stop they don't count."""
    if known is None:
        return []
    try:
        text = _read(path)
        if text is None:
            return []
        known_set = set(known)
        return [finding for finding in _scan(relative, text) if finding["id"] not in known_set and _is_serious(finding)
                and (noting or finding["rule"] not in FAKES)]
    except Exception:  # occam: ignore[swallowed-exception] fails open, like identities
        return []


def still_raised_note(files: list[tuple[Path, str]]) -> str | None:
    """For an audit, what the scanner still raises in files it changed. A report calling one of these fixed is wrong, whoever wrote the code."""
    found: list[dict] = []
    for path, relative in within_budget(files, AUDIT_FILES_AT_STOP):
        try:
            text = _read(path)
            found += [finding for finding in _scan(relative, text) if _is_serious(finding) and finding["rule"] not in FAKES] if text is not None else []
        except Exception:  # occam: ignore[swallowed-exception] fails open, like identities
            continue
    if not found:
        return None
    return ("The scanner still raises these in files you changed: " + describe(found, limit=12) +
            ". If your report calls one fixed, it isn't, so fix it or say that it remains. Check each other fix you claim against the diff too.")


def known_findings(event: dict, session, relative: str) -> list[str] | None:
    for entry in session.entries:
        if entry.get("kind") == "scan-baseline" and entry.get("name") == relative:
            return entry.get("ids")
    return committed_identities(Path(event.get("cwd") or os.getcwd()), relative)


def occam_subcommand(words: list[str]) -> tuple[str, list[str]] | None:
    """If this shell command runs occam's own tool: its subcommand and the arguments after it."""
    for index, word in enumerate(words):
        if os.path.basename(word.strip("'\"")) == "occam.py" and index + 1 < len(words):
            return words[index + 1], words[index + 2:]
    return None


def describe(findings: list[dict], limit: int = MAX_LISTED) -> str:
    listed = [f"{finding['path']}:{finding['line']} {finding['rule']}: {finding['message']}" for finding in findings[:limit]]
    extra = f" and {len(findings) - limit} more" if len(findings) > limit else ""
    return "; ".join(listed) + extra
