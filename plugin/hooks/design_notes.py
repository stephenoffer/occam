"""Says what the repository's design doc decided about a file, once, when an agent edits it. Nothing here holds anything, and any failure says nothing.

This costs words only where a decision applies, so a repository with no design doc pays nothing. It fires for subagents too, which never see what a session started with.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import shlex
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "occam" / "scripts"))

_TOOL = Path(__file__).resolve().parents[1] / "skills" / "occam" / "scripts" / "occam.py"
_LARGEST_DOCUMENT = 200_000  # far past what the tool calls too long, and a hook has seconds


def _root_of(path: Path, cwd: str | None) -> Path | None:
    """The repository a path is in, by its nearest `.git`, without starting a process on every edit. A worktree has its own `.git`. Outside git, the project folder."""
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            return folder
    for folder in (os.environ.get("CLAUDE_PROJECT_DIR"), cwd):
        if folder and path.is_relative_to(os.path.realpath(folder)):
            return Path(os.path.realpath(folder))
    return None


def session_note(cwd: str | None) -> str:
    """A pointer, not the document: a full context file costs tokens on every turn, and Gloaguen et al. found no improvement in task success from them."""
    try:
        from occam_tools import design
        root = _root_of(Path(os.path.realpath(cwd or ".")), cwd)
        name = design.find(root) if root else None
    except Exception:  # a hook must never fail because of this
        return ""
    if not name:
        return ""
    return f" This repository keeps {name}, its shared design. `python3 {shlex.quote(str(_TOOL))} design for <path> --root {shlex.quote(str(root))}` shows what it says about a file, and where it and the code disagree about what exists, the code is right."


def on_edit(event: dict, file_path: str, session, record: Callable, context: Callable) -> dict | None:
    """The decisions in force on this file, the first time this agent edits it. Subagents share a session, and none of them saw the others' notes."""
    try:
        from occam_tools import design, files as filesystem
        cwd = event.get("cwd") or os.getcwd()
        path = Path(os.path.realpath(os.path.join(cwd, file_path)))
        root = _root_of(path, cwd)
        name = design.find(root) if root else None
        relative = path.relative_to(root).as_posix() if name else ""
        key = f"design:{event.get('agent_id') or ''}:{root}:{relative}"
        if not name or relative == name or session.has("mentioned", key):
            return None
        text = filesystem.read_text(root / name)
        found = design.decisions_on(design.parse(text), relative) if text and len(text) <= _LARGEST_DOCUMENT else []
    except Exception:  # a hook must never fail because of this
        return None
    if not found:
        return None
    record(event, kind="mentioned", name=key)
    listed = "; ".join(design.clip(decision.raw[2:].rstrip(".")) for decision in found[:design.MAX_DECISIONS_IN_A_NOTE])
    more = f" and {len(found) - design.MAX_DECISIONS_IN_A_NOTE} more" if len(found) > design.MAX_DECISIONS_IN_A_NOTE else ""
    return context("PostToolUse", f"occam: {name} has decisions on {relative}: {listed}{more}. These stand until a later one supersedes them, so a change that departs from one should say so and record it.")
