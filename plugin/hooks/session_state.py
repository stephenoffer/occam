"""What has happened in a session: one JSON line per hook event, kept in the plugin's data directory.

It comes only from documented hook events. It doesn't parse the transcript, whose format is undocumented and which may lag behind.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import json
import os
import re
import tempfile
from pathlib import Path


def state_file(session_id: str | None) -> Path:
    uid = getattr(os, "getuid", lambda: "user")()
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.join(tempfile.gettempdir(), f"occam-{uid}")
    folder = Path(base) / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown") + ".jsonl")


def record(event: dict, **entry) -> None:
    with open(state_file(event.get("session_id")), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


class Session:
    """What has happened so far, derived from recorded hook events."""

    def __init__(self, event: dict) -> None:
        path = state_file(event.get("session_id"))
        self.entries: list[dict] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
                try:
                    self.entries.append(json.loads(line))
                except ValueError:
                    continue
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
