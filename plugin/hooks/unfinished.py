"""What the record shows was left undone at Stop: a report admitting part of the request wasn't done, and a changed notebook that can't run.

These are where runs without any skill fail, so they are where a second look can change the result. Each fires once per session,
because an agent that still disagrees after one challenge has heard the point. docs/failure-modes.md lists the ways around them.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
from pathlib import Path
from typing import Callable

import occam_evidence as evidence
import scan_notes

_WORK = r"(?:split|moved?|extract\w*|migrat\w*|port\w*|convert\w*|implement\w*|refactor\w*|broke|pulled|finish\w*|complet\w*)"
# Measured on 259 saved reports. Sentences about what was checked, or about nearby issues, are deliberately not matched:
# the core skill asks for those, and challenging them would push agents into work nobody requested.
STOPPED_SHORT = re.compile(
    rf"\bI\b[^.\n]{{0,25}}\b{_WORK}\b[^.\n]{{0,25}}\b(?:only|just)\b"
    rf"|\bI\b[^.\n]{{0,15}}\b(?:only|just)\b[^.\n]{{0,15}}\b{_WORK}\b"
    r"|\bthe rest\b(?:[^.\n]|\.\w){0,70}\b(?:stay put|stays put|ha(?:s|ve) to stay|stayed|remains?|unchanged|untouched|left (?:in|as|for))\b"
    r"|\b(?:didn'?t|did not|haven'?t|won'?t|stopped short of|leave|left)\b[^.\n]{0,40}\bthe rest\b"
    r"|\b(?:splitting|moving|finishing|migrating|converting) the rest\b"
    r"|^\W*(?:why I didn'?t|what stayed|what I left)\b", re.I | re.M)
AS_REQUESTED = re.compile(r"\bas (?:you )?(?:asked|requested)\b|\byou asked\b|\bper your\b", re.I)
HIDDEN_STATE = "nb-hidden-state"
MAX_FOLDERS_SEARCHED = 2000


def stopped_short(message: str) -> str | None:
    """The sentence admitting that part of the request wasn't done, unless the request itself was for only that part."""
    return next((sentence.strip() for sentence in evidence.sentences_of(message)
                 if STOPPED_SHORT.search(sentence) and not AS_REQUESTED.search(sentence)), None)


def _located(path: Path, root: str) -> Path:
    """Where a notebook is. An earlier command's `cd` can make its recorded path relative to somewhere else, so look for its name, briefly."""
    if path.exists() or path.suffix != ".ipynb":
        return path
    for seen, (folder, folders, names) in enumerate(os.walk(root)):
        folders[:] = [name for name in folders if not name.startswith(".") and name not in ("node_modules", "__pycache__")]
        if path.name in names:
            return Path(folder, path.name)
        if seen >= MAX_FOLDERS_SEARCHED:
            break
    return path


def unrunnable_notebook(path: Path, relative: str) -> list[str]:
    """Why this notebook fails when run top to bottom, from a static read of its cells. Nothing in it is executed."""
    if not relative.endswith(".ipynb"):
        return []
    try:
        text = scan_notes._read(path)
        findings = scan_notes._scan(relative, text) if text is not None else []
    except Exception:  # occam: ignore[swallowed-exception] fails open, like the scanner notes
        return []
    return [finding["message"] for finding in findings if finding["rule"] == HIDDEN_STATE]


def changed_in_git(root: Path) -> list[str]:
    """What git says changed, for an edit whose path couldn't be read from its command. Empty without git, which reads as nothing to add."""
    try:
        from occam_tools.files import run_git

        status = run_git(root, "status", "--porcelain", "--no-renames", timeout=5)
    except Exception:  # occam: ignore[swallowed-exception] fails open, like the scanner notes
        return []
    lines = (line[3:].strip().strip('"') for line in (status or "").splitlines() if line[:2] != "??" and not line.startswith(" D") and not line.startswith("D "))
    return [line for line in lines if line]


def notes(event: dict, session, message: str, files: list[tuple[Path, str]], record: Callable[..., None]) -> list[str]:
    """What to send back. `session` and `record` are the hook's own, passed in so this module doesn't import it."""
    found = []
    quoted = stopped_short(message)
    if quoted and not session.has("mentioned", "stopped-short"):
        record(event, kind="mentioned", name="stopped-short")
        found.append(f"The message says part of the request wasn't done: \"{quoted[:200]}\". A reason isn't a stop unless finishing would break "
                     "a constraint the request states or needs a decision only a person can make. If a way through exists inside those "
                     "constraints, the rest belongs in this turn. If none does, the report should name the one decision needed and what was tried.")
    for path, relative in files:
        key = f"unrunnable:{relative}"
        reasons = unrunnable_notebook(_located(path, event.get("cwd") or "."), relative)
        if reasons and not session.has("mentioned", key):
            record(event, kind="mentioned", name=key)
            found.append(f"{relative} can't run top to bottom: {' '.join(reasons[:3])} This turn changed that notebook, and whoever reruns it gets "
                         "an error or a different number. Saved output and cells run in a hand-picked order don't show otherwise. Moving cells "
                         "keeps their content, and running them in saved order in one fresh namespace settles it. If the request rules that "
                         "out, the report should say so up front.")
    return found
