"""Points documentation work at the skill and the check made for it. Nothing here holds anything."""

from __future__ import annotations  # the stock macOS python3 is 3.9

import re
from pathlib import Path
from typing import Callable

from occam_evidence import AGENT_INSTRUCTIONS
from scale_notes import TOOL

REQUEST = re.compile(r"\b(?:write|draft|add|generate|create|make|update|improve|rewrite|polish)\b[^.?!\n]{0,60}"
                     r"\b(?:docs?|documentation|readme|api reference|docstrings?|changelog|release notes|user guide|usage guide|tutorial)\b"
                     r"|\bdocument (?:this|the|these|how|what|our|my)\b", re.I)
SKILL = "occam-docs"
_SUFFIXES = {".md", ".markdown", ".mdx", ".rst"}
POINTER = ("occam: for documentation, the `occam:occam-docs` skill covers writing it from the code, then a prose pass with `human-voice` "
           f"if that's installed. `{TOOL} docs <file>` checks its names, paths, flags, links and example syntax against the code, "
           "and runs the human-voice linter if it can find one.")


def is_document(relative: str) -> bool:
    """Prose for readers. Files that steer agents get a note of their own."""
    return Path(relative).suffix.lower() in _SUFFIXES and not AGENT_INSTRUCTIONS.search(relative.replace("\\", "/"))


def once(session, mention: Callable[[str], None]) -> str | None:
    """The pointer, once per session and never after the skill has loaded."""
    if session.has("skill", SKILL) or session.has("mentioned", SKILL):
        return None
    mention(SKILL)
    return POINTER
