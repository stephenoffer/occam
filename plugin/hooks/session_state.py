"""What has happened in a session: one JSON line per hook event, kept in the plugin's data directory.

It comes only from documented hook events. It doesn't parse the transcript, whose format is undocumented and which may lag behind.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path


def private_folder(folder: Path) -> Path:
    """Prompts and commands are kept here, so the folder is this user's alone: made 0700, and refused if it's a link or someone
    else's, which a shared temp folder lets another user arrange first. Refusing fails the hook open, as any other failure does."""
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if hasattr(os, "getuid"):
        for place in (folder, folder.parent):
            info = os.lstat(place) if place == folder else os.stat(place)
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
                raise PermissionError(f"{place} isn't this user's own folder, so occam keeps no session state there")
        if os.stat(folder).st_mode & 0o077:
            os.chmod(folder, 0o700)
    return folder


def state_file(session_id: str | None) -> Path:
    uid = getattr(os, "getuid", lambda: "user")()
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.join(tempfile.gettempdir(), f"occam-{uid}")
    return private_folder(Path(base) / "sessions") / (re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown") + ".jsonl")


def record(event: dict, **entry) -> None:
    descriptor = os.open(state_file(event.get("session_id")), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with open(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def prune(event: dict, seconds: float) -> None:
    """Sessions this old are finished with."""
    folder = state_file(event.get("session_id")).parent
    for old in [*folder.glob("*.jsonl"), *folder.glob("*.card")]:
        try:
            if time.time() - old.stat().st_mtime > seconds:
                old.unlink()
        except OSError:
            continue


def _failures(event: dict) -> Path:
    return state_file(event.get("session_id")).parent / "failed-open.log"


def note_failure(event: dict, handler: str, error: BaseException) -> None:
    """A hook that fails open lets an action through unchecked, so it's kept where the next session start can tell the person."""
    try:
        with open(os.open(_failures(event), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": int(time.time()), "hook": handler, "error": f"{type(error).__name__}: {error}"[:300]}) + "\n")
    except OSError:
        pass


def with_failures_told(event: dict, result: dict | None) -> dict | None:
    """Failures since the last session start, said once to the person, who otherwise can't tell a quiet hook from a broken one."""
    path = _failures(event)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        path.unlink()  # before reading the lines, so one that can't be read can't keep the log forever
    except OSError:
        return result
    lines = []
    for line in text.splitlines():
        try:
            lines.append(json.loads(line))
        except ValueError:
            lines.append({"hook": "?", "error": "a line that couldn't be read"})
    lines = [line if isinstance(line, dict) else {"hook": "?", "error": "?"} for line in lines]
    if not lines:
        return result
    last = lines[-1]
    message = (f"occam's hooks failed open {len(lines)} times since a session last started, so those actions went through unchecked. "
               f"The latest, in {last.get('hook')}: {last.get('error')}")
    return {**(result or {}), "systemMessage": message}


_READ: dict[str, tuple[tuple, list[dict]]] = {}  # within one hook run: a file read again unchanged needn't be parsed again


def _entries(path: Path) -> list[dict]:
    """The recorded entries. A file whose inode, size and modification time are what they were when it was last read here is that file
    unchanged, since every write appends, so it isn't parsed again; anything else is read whole."""
    try:
        info = path.stat()
    except OSError:
        return []
    key = (info.st_ino, info.st_size, info.st_mtime_ns)
    known = _READ.get(str(path))
    if known and known[0] == key:
        return list(known[1])
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):  # anything else wasn't written here, and one such line mustn't switch the hooks off
            entries.append(entry)
    _READ[str(path)] = (key, entries)
    return list(entries)


class Session:
    """What has happened so far, derived from recorded hook events."""

    def __init__(self, event: dict) -> None:
        path = state_file(event.get("session_id"))
        self.entries: list[dict] = _entries(path)
        start = max((i for i, e in enumerate(self.entries) if e.get("kind") == "prompt"), default=-1)
        self.prompt_entry = self.entries[start] if start >= 0 else {}
        self.turn = self.entries[start + 1:]
        self.prompt = self.prompt_entry.get("text", "")
        self.read_only = bool(self.prompt_entry.get("read_only")) and not any(e.get("kind") == "approved" for e in self.turn)

    def has(self, kind: str, name: str | None = None) -> bool:
        return any(e.get("kind") == kind and (name is None or e.get("name") == name) for e in self.entries)

    def count(self, kind: str, name: str) -> int:
        return sum(1 for e in self.entries if e.get("kind") == kind and e.get("name") == name)

    def code_edits(self) -> list[dict]:
        return [e for e in self.turn if e.get("kind") == "edit" and e.get("code")]

    def after_last_edit(self, kind: str) -> list[dict]:
        last = max(i for i, e in enumerate(self.turn) if e.get("kind") == "edit" and e.get("code"))
        return [e for e in self.turn[last + 1:] if e.get("kind") == kind]
