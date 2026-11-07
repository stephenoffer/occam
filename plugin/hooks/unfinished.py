"""What the record shows was left undone at Stop: a report admitting part of the request wasn't done, and a changed notebook that can't run.

These are where runs without any skill fail, so they are where a second look can change the result. Each fires once, a report per request and a notebook per session,
because an agent that still disagrees after one challenge has heard the point. docs/failure-modes.md lists the ways around them.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import json
import re
from pathlib import Path
from typing import Callable

import occam_evidence as evidence
import scan_notes

_WORK = r"(?:split|moved?|extract\w*|migrat\w*|port\w*|convert\w*|implement\w*|refactor\w*|broke|pulled|finish\w*|complet\w*)"
# Measured on saved reports. Sentences about what was checked, about nearby issues, or about what a fix left alone are deliberately not
# matched: the core skill asks for those, and challenging them would push agents into work nobody requested.
STOPPED_SHORT = re.compile(
    rf"\b(?:I|we)\s+{_WORK}(?:\s+out)?\s+only\s+(?:the|a|an|part|some|\d+|two|three|four|five)\b"
    rf"|\b(?:I|we)\s+only\s+{_WORK}\b"
    rf"|^\W*{_WORK}\s+only\s+(?:the|a|an|part|some|\d+|two|three|four|five)\b"
    r"|\bthe rest\b(?:[^.\n]|\.\w){0,70}\b(?:stay put|stays put|ha(?:s|ve) to stay|must stay)\b"
    rf"|\b(?:didn't|did not|haven't|have not|won't|couldn't|could not|stopped short of)\s+{_WORK}\b[^.\n]{{0,40}}\bthe (?:rest|remaining)\b"
    r"|\b(?:splitting|moving|finishing|migrating|converting) the rest\b"
    r"|\b(?:I|we)\s+(?:didn't|did not|haven't|have not|couldn't|could not)\s+(?:finish|complete)\b"
    rf"|\b(?:I|we)\s+{_WORK}\s+(\d+) of (?:the )?(\d+)\b|\bonly (\d+) of (?:the )?(\d+)\b"
    r"|\bremaining \w+ (?:still )?need to\b|\bremaining \w+ still need\b"
    r"|\bleft\b[^.\n]{0,40}\bfor (?:later|a follow-?up)\b"
    r"|\b(?:migration|split|refactor|port|conversion|move|work|change) is (?:incomplete|partial|unfinished)\b"
    r"|^\W*(?:why I didn't|what stayed|not done\b)", re.I | re.M)
AS_REQUESTED = re.compile(r"\bas (?:you )?(?:asked|requested)\b(?<!not all of them as you asked)|\bper your\b", re.I)
NOT_ALL = re.compile(r"\bnot all\b", re.I)
# Reporting something else that was noticed, which the core skill asks for, rather than something asked for.
NOT_THE_REQUEST = re.compile(r"\b(?:unrelated|out of scope|nobody asked|didn't ask|did not ask|not asked|wasn't part|not part of the request|nearby)\b", re.I)
HIDDEN_STATE = "nb-hidden-state"
MAX_NOTEBOOK_BYTES = 20_000_000


def stopped_short(message: str) -> str | None:
    """The sentence admitting that part of the request wasn't done, unless the request itself was for only that part, or it's about something else."""
    for sentence in evidence.sentences_of(message.replace("\u2019", "'")):
        match = STOPPED_SHORT.search(sentence)
        if not match or NOT_THE_REQUEST.search(sentence) or (AS_REQUESTED.search(sentence) and not NOT_ALL.search(sentence)):
            continue
        counts = [int(group) for group in match.groups() if group]
        if len(counts) == 2 and counts[0] >= counts[1]:  # `I migrated 5 of 5`
            continue
        return sentence.strip()
    return None


def unrunnable_notebook(path: Path, relative: str) -> list[str]:
    """Why this notebook fails when run top to bottom, from a static read of its cells. Nothing in it is executed."""
    if not relative.endswith(".ipynb"):
        return []
    try:
        if not path.is_file() or path.stat().st_size > MAX_NOTEBOOK_BYTES:  # not reading a FIFO, which would block
            return []
        notebook = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        for cell in notebook.get("cells", []):  # saved outputs can be most of a notebook, and say nothing about whether it runs
            cell.pop("outputs", None)
        findings = scan_notes._scan(relative, json.dumps(notebook))
    except (Exception, scan_notes._TooSlow):  # occam: ignore[swallowed-exception] fails open, like the scanner notes
        return []
    return [finding["message"] for finding in findings if finding["rule"] == HIDDEN_STATE]


def changed_in_git(root: Path, since: float | None = None) -> list[str]:
    """What git says changed this turn, for an edit whose path couldn't be read. Empty without git, which reads as nothing to add."""
    try:
        from occam_tools.files import run_git

        status = run_git(root, "status", "--porcelain", "--no-renames", timeout=3)
    except Exception:  # occam: ignore[swallowed-exception] fails open, like the scanner notes
        return []
    found = []
    for line in (status or "").splitlines():
        path = line[3:].strip().strip('"')
        if path and line[:2] != "??" and "D" not in line[:2] and _changed_since(root / path, since):
            found.append(path)
    return found


def _changed_since(path: Path, since: float | None) -> bool:
    """Someone's uncommitted work from before this turn is theirs, and not something this turn's report answers for."""
    try:
        return since is None or path.stat().st_mtime >= since
    except OSError:
        return False


def _unrunnable_text(relative: str, reasons: list[str], ours: bool) -> str:
    whose = ("This turn changed that notebook, and whoever reruns it gets an error or a different number. "
             if ours else "That notebook changed while this ran, possibly by someone else, in which case it isn't this report's to answer for. If it was this work, whoever reruns it gets an error or a different number. ")
    return (f"{relative} can't run top to bottom: {' '.join(reasons[:3])} {whose}Saved output and cells run in a hand-picked order don't show otherwise. "
            "Moving cells keeps their content, and running them in saved order in one fresh namespace settles it. If the request rules that out, the report should say so up front.")


def notes(event: dict, session, message: str, files: list[tuple[Path, str]], unclear: list[tuple[Path, str]], turn: list[dict], record: Callable[..., None]) -> list[str]:
    """What to send back. `session` and `record` are the hook's own, passed in so this module doesn't import it.

    `files` are what this turn's commands named. `unclear` is what else changed while a command that hid its target ran, which in a shared tree can be anyone's.
    """
    found = []
    quoted = stopped_short(message)
    if quoted and not any(entry.get("kind") == "mentioned" and entry.get("name") == "stopped-short" for entry in turn):
        record(event, kind="mentioned", name="stopped-short")
        found.append(f"The message says part of the request wasn't done: \"{quoted[:200]}\". A reason isn't a stop unless finishing would break "
                     "a constraint the request states or needs a decision only a person can make. If a way through exists inside those "
                     "constraints, the rest belongs in this turn. If none does, the report should name the one decision needed and what was tried.")
    named = {relative for _, relative in files}
    for path, relative in scan_notes.within_budget([item for item in files + unclear if item[1].endswith(".ipynb")]):
        key = f"unrunnable:{relative}"
        reasons = unrunnable_notebook(path, relative)
        if reasons and not session.has("mentioned", key):
            record(event, kind="mentioned", name=key)
            found.append(_unrunnable_text(relative, reasons, relative in named))
    return found
