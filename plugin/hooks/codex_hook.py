#!/usr/bin/env python3
"""Codex hooks for occam: hold edits on a read-only request, mention serious findings an edit introduced, and send the agent back once before it stops.

Smaller than the Claude Code hook on purpose. Codex skips plugin hooks until the user has reviewed and trusted them, and its
docs call hooks a guardrail, not an enforcement boundary. Written against the documented protocol. Not yet run under Codex itself.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

import scan_notes  # beside this script, on sys.path because Python put it there
from occam_hook import AUDIT_REQUEST, could_lose_work, is_code, reads_as_read_only, shell_edits, visible_prompt

_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)


def _state_file(session_id: str | None) -> Path:
    base = os.environ.get("PLUGIN_DATA") or os.path.join(tempfile.gettempdir(), f"occam-codex-{getattr(os, 'getuid', lambda: 'user')()}")
    folder = Path(base) / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown") + ".json")


def _load(session_id: str | None) -> dict:
    state = {"edited": [], "noted": [], "baselines": {}, "read_only": False, "audit": False}
    try:
        state.update(json.loads(_state_file(session_id).read_text()))
    except (OSError, ValueError):
        pass
    return state


def _save(session_id: str | None, state: dict) -> None:
    _state_file(session_id).write_text(json.dumps(state))


def _edited_paths(event: dict) -> list[str]:
    tool_input = event.get("tool_input") or {}
    if event.get("tool_name") == "apply_patch":
        return _PATCH_FILE.findall(tool_input.get("command") or "")
    path = tool_input.get("file_path")
    return [path] if path else []


def _relative(event: dict, path: str) -> str | None:
    cwd = os.path.realpath(event.get("cwd") or os.getcwd())
    absolute = os.path.realpath(os.path.join(cwd, path))
    return os.path.relpath(absolute, cwd) if absolute.startswith(cwd + os.sep) else None


def _introduced(event: dict, state: dict, relative: str) -> list[dict]:
    """Only what this work added. Without a recorded baseline or a committed version, nothing can be attributed to it."""
    root = Path(event.get("cwd") or os.getcwd())
    known = state["baselines"].get(relative)
    if known is None:
        known = scan_notes.committed_identities(root, relative)
    return scan_notes.introduced(root / relative, relative, known)


def user_prompt(event: dict) -> dict | None:
    state = _load(event.get("session_id"))
    words = visible_prompt(event.get("prompt") or "")
    state["read_only"] = reads_as_read_only(words)
    state["audit"] = bool(AUDIT_REQUEST.search(words))
    _save(event.get("session_id"), state)
    return None


def pre_tool(event: dict) -> dict | None:
    state = _load(event.get("session_id"))
    named = _edited_paths(event)
    command = (event.get("tool_input") or {}).get("command") or ""
    writes = bool(named) or (event.get("tool_name") == "Bash" and could_lose_work(shell_edits(command, event), command, event))
    if state["read_only"] and writes:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": (
            "occam: the current request reads as review-only, audit-only or plan-only, so edits to project files are held for this turn. "
            "Findings go in the report. If the request did authorize edits, the user can say so, for example with \"go ahead\".")}}
    root = Path(event.get("cwd") or os.getcwd())
    for relative in filter(None, (_relative(event, path) for path in named)):
        if is_code(relative) and relative not in state["baselines"]:
            state["baselines"][relative] = scan_notes.identities(root / relative, relative)
    _save(event.get("session_id"), state)
    return None


def post_tool(event: dict) -> dict | None:
    session = event.get("session_id")
    state = _load(session)
    fresh: list[dict] = []
    for path in _edited_paths(event):
        relative = _relative(event, path)
        if relative:
            if relative not in state["edited"]:
                state["edited"].append(relative)
            fresh += [finding for finding in _introduced(event, state, relative) if finding["id"] not in state["noted"]]
    state["noted"] += [finding["id"] for finding in fresh]
    _save(session, state)
    if not fresh:
        return None
    note = "occam scan of this edit: " + scan_notes.describe(fresh) + ". These are leads. If one is real, this is the moment to fix it."
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}


def stop(event: dict) -> dict | None:
    if event.get("stop_hook_active"):
        return None
    state = _load(event.get("session_id"))
    found = [finding for relative in scan_notes.within_budget(state["edited"]) for finding in _introduced(event, state, relative)]
    root = Path(event.get("cwd") or os.getcwd())
    remaining = scan_notes.still_raised_note([(root / relative, relative) for relative in state["edited"]]) if state["audit"] else None
    if not found and not remaining:
        return None
    introduced = ("the scanner sees these in what you changed, and they weren't there before: " + scan_notes.describe(found) +
                  ". Fix each one, or say in your report why it's fine. ") if found else ""
    return {"decision": "block", "reason": "occam: " + introduced + (remaining or "")}


HANDLERS = {"user-prompt": user_prompt, "pre-tool": pre_tool, "post-tool": post_tool, "stop": stop}


def main(argv: list[str]) -> int:
    if os.environ.get("OCCAM_HOOKS", "").lower() in ("off", "0", "false") or len(argv) != 2 or argv[1] not in HANDLERS:
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
        result = HANDLERS[argv[1]](event if isinstance(event, dict) else {})
        if result:
            print(json.dumps(result))
    except Exception as error:  # occam: ignore[swallowed-exception] fails open, because a broken hook must not wedge a session
        print(f"occam hook failed open: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
