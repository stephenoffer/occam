#!/usr/bin/env python3
"""Codex hooks for occam: hold edits on a read-only request, mention serious findings an edit introduced, and send the agent back once before it stops.

Smaller than the Claude Code hook on purpose. Codex skips plugin hooks until the user has reviewed and trusted them, and its
docs call hooks a guardrail, not an enforcement boundary. Written against the documented protocol. Not yet run under Codex itself.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import tempfile
import time
from pathlib import Path

import scan_notes  # beside this script, on sys.path because Python put it there
from classify import AUDIT_REQUEST, CONTINUES, asks_to_act, asks_to_change, command_read_only, declines, is_code, reads_as_read_only, visible_prompt
from session_state import private_folder
from shell_writes import could_lose_work, shell_edits

try:
    import fcntl
except ImportError:  # Windows: no lock, as before
    fcntl = None

# A rename is an Update with a "Move to" line, and the file it leaves behind and the one it makes are both edited.
_PATCH_FILE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.M)


def _state_file(session_id: str | None) -> Path:
    base = os.environ.get("PLUGIN_DATA") or os.path.join(tempfile.gettempdir(), f"occam-codex-{getattr(os, 'getuid', lambda: 'user')()}")
    return private_folder(Path(base) / "sessions") / (re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown") + ".json")


def _load(session_id: str | None) -> dict:
    state = {"edited": [], "noted": [], "baselines": {}, "read_only": False, "audit": False}
    try:
        saved = json.loads(_state_file(session_id).read_text())
    except (OSError, ValueError):
        return state
    if isinstance(saved, dict):  # anything else wasn't written here, and mustn't switch the hook off
        state.update(saved)
    return state


def _save(session_id: str | None, state: dict) -> None:
    """Whole or not at all, so a hook reading at the same moment never sees half a file and starts again from nothing."""
    path = _state_file(session_id)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(json.dumps(state))
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def _edited_paths(event: dict) -> list[str]:
    tool_input = event.get("tool_input") or {}
    if event.get("tool_name") == "apply_patch":
        return [path.strip() for path in _PATCH_FILE.findall(tool_input.get("command") or "")]
    path = tool_input.get("file_path")
    return [path] if path else []


def _project(event: dict) -> str:
    """The repository the session works in, which can be above the folder Codex runs in: the nearest folder holding `.git`, found
    without running git, else the working folder."""
    cwd = os.path.realpath(event.get("cwd") or os.getcwd())
    folder = cwd
    while not os.path.exists(os.path.join(folder, ".git")):
        if os.path.dirname(folder) == folder:
            return cwd
        folder = os.path.dirname(folder)
    return folder


def _relative(event: dict, path: str) -> str | None:
    root = _project(event)
    absolute = os.path.realpath(os.path.join(event.get("cwd") or os.getcwd(), path))
    return os.path.relpath(absolute, root) if absolute.startswith(root + os.sep) else None


def _introduced(event: dict, state: dict, relative: str, noting: bool = False) -> list[dict]:
    """Only what this work added. Without a recorded baseline or a committed version, nothing can be attributed to it."""
    root = Path(_project(event))
    known = state["baselines"].get(relative)
    if known is None:
        known = scan_notes.committed_identities(root, relative)
    return scan_notes.introduced(root / relative, relative, known, noting=noting)


def user_prompt(event: dict) -> dict | None:
    state = _load(event.get("session_id"))
    prompt = event.get("prompt") or ""
    words = visible_prompt(prompt)
    asked, changing, was_read_only = bool(state.get("asked")), bool(state.get("changing")), bool(state["read_only"])
    state["declined"] = declines(words, asked)
    state["asked"] = False  # answered, so a turn that never reaches Stop can't carry it into the next prompt
    by_command = command_read_only(prompt)
    # A "continue" after anything but a question about changing the code carries on the previous request, hold and all.
    continued = bool(CONTINUES.match(words)) and not changing and was_read_only
    state["read_only"] = (reads_as_read_only(words) if by_command is None else by_command) or state["declined"] or continued
    state["audit"] = bool(AUDIT_REQUEST.search(words))
    _save(event.get("session_id"), state)
    return None


def pre_tool(event: dict) -> dict | None:
    state = _load(event.get("session_id"))
    named = _edited_paths(event)
    command = (event.get("tool_input") or {}).get("command") or ""
    writes = bool(named) or (event.get("tool_name") == "Bash" and could_lose_work(shell_edits(command, event), command, event))
    if state["read_only"] and writes:
        reason = ("occam: you asked whether to go ahead with this work, and the user said no, so edits to project files are held for this turn. "
                  "Answer them without making the change. If they want it later, they can say so, for example with \"go ahead\".") if state.get("declined") else (
            "occam: the current request reads as review-only, audit-only or plan-only, so edits to project files are held for this turn. "
            "Findings go in the report. If the request did authorize edits, the user can say so, for example with \"go ahead\".")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}
    root = Path(_project(event))
    for relative in filter(None, (_relative(event, path) for path in named)):
        if is_code(relative) and relative not in state["baselines"]:
            state["baselines"][relative] = scan_notes.identities(root / relative, relative)
    _save(event.get("session_id"), state)
    return None


# Codex's own words for a patch it refused before writing anything (from its binary, 26.1021). One that failed later, "Failed to apply
# patch" or a nonzero exit, may have written some files, so it still counts as an edit: a missed edit costs more than a rescan.
_NOTHING_WRITTEN = re.compile(r"^\s*(?:apply_patch verification failed|patch rejected|invalid patch|invalid hunk)", re.I | re.M)


def _failed(response) -> bool:
    """A patch that wrote nothing. For a local tool Codex sends the output the model sees (its hooks page), so that text is read."""
    text = response.get("output") if isinstance(response, dict) else response
    return isinstance(text, str) and bool(_NOTHING_WRITTEN.search(text))


def post_tool(event: dict) -> dict | None:
    session = event.get("session_id")
    state = _load(session)
    fresh: list[dict] = []
    for path in [] if _failed(event.get("tool_response")) else _edited_paths(event):
        relative = _relative(event, path)
        if relative:
            if relative not in state["edited"]:
                state["edited"].append(relative)
            fresh += [finding for finding in _introduced(event, state, relative, noting=True) if finding["id"] not in state["noted"]]
    state["noted"] += scan_notes.ids_of(fresh)
    _save(session, state)
    if not fresh:
        return None
    note = "occam scan of this edit: " + scan_notes.describe(fresh) + ". These are leads. If one is real, this is the moment to fix it."
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}


def stop(event: dict) -> dict | None:
    state = _load(event.get("session_id"))
    if not event.get("agent_id"):
        state["asked"] = asks_to_act(event.get("last_assistant_message") or "")  # a "no" to it holds the next turn's edits
        state["changing"] = asks_to_change(event.get("last_assistant_message") or "")
        _save(event.get("session_id"), state)
    # Edits are held on a read-only turn, so asking for a fix there would only send the agent into the hold.
    if event.get("stop_hook_active") or state["read_only"]:
        return None
    found = [finding for relative in scan_notes.within_budget(state["edited"]) for finding in _introduced(event, state, relative)]
    root = Path(_project(event))
    remaining = scan_notes.still_raised_note([(root / relative, relative) for relative in state["edited"]]) if state["audit"] else None
    if not found and not remaining:
        return None
    introduced = ("the scanner sees these in what you changed, and they weren't there before: " + scan_notes.describe(found) +
                  ". Fix each one, or say in your report why it's fine. ") if found else ""
    return {"decision": "block", "reason": "occam: " + introduced + (remaining or "")}


HANDLERS = {"user-prompt": user_prompt, "pre-tool": pre_tool, "post-tool": post_tool, "stop": stop}
HOOK_SECONDS = 8  # as the Claude Code hook allows itself: past it, failing open beats being killed mid-write


class _OutOfTime(BaseException):
    """Not an Exception, so a best-effort `except Exception` inside can't swallow it."""


def _out_of_time(*_) -> None:
    raise _OutOfTime(f"past {HOOK_SECONDS}s")


def _lock(handle) -> None:
    """Wait a while for another of this session's hooks, then go on without the lock: a lost update beats a session that hangs."""
    deadline = time.monotonic() + 3
    while fcntl:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() > deadline:
                return
            time.sleep(0.05)


def main(argv: list[str]) -> int:
    level = os.environ.get("OCCAM_HOOKS", "").strip().lower()
    if level in ("off", "0", "false") or len(argv) != 2 or argv[1] not in HANDLERS:
        return 0
    timed = hasattr(signal, "setitimer")
    try:
        if timed:
            signal.signal(signal.SIGALRM, _out_of_time)
            signal.setitimer(signal.ITIMER_REAL, HOOK_SECONDS)
        event = json.loads(sys.stdin.read() or "{}")
        event = event if isinstance(event, dict) else {}
        with open(str(_state_file(event.get("session_id"))) + ".lock", "a") as lock:  # one event at a time per session, so none loses another's update
            _lock(lock)
            result = HANDLERS[argv[1]](event)
        if level == "guard":  # only a decision gets through, as in occam_hook.guard_only
            output = (result or {}).get("hookSpecificOutput") or {}
            result = result if output.get("permissionDecision") in ("ask", "deny") else None
        if result:
            print(json.dumps(result))
    except (Exception, _OutOfTime) as error:  # occam: ignore[swallowed-exception] fails open, because a broken hook must not wedge a session
        print(f"occam hook failed open: {type(error).__name__}: {error}", file=sys.stderr)
    finally:
        if timed:
            signal.setitimer(signal.ITIMER_REAL, 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
