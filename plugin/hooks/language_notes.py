"""Where each language's guidance is, and which languages a request or a project names.

The language skills are helpers, routed rather than listed: they carry disable-model-invocation, so only the front doors cost text in
every session (DESIGN `routed-helpers`, the owner's decision of 2026-11-08). The Skill tool can't load them then, so the notes give the
file to read, on the first edit in a language and on a review, which makes no edit to show its language.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
from pathlib import Path

import scale_notes
from classify import LANGUAGE_MARKERS, LANGUAGE_NAMES, LANGUAGE_PROMPTS, LANGUAGE_RISKS

# A read of a routed skill's text counts as loading it, in any path form. The core is always loaded with the Skill tool.
SKILL_FILE = re.compile(r"(?:^|[\\/\s\"'`])(occam-[\w-]+)[\\/]SKILL\.md\b")


def skill_path(skill: str) -> str:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parents[1])
    return str(Path(root) / "skills" / skill / "SKILL.md")


def note(languages: list[str]) -> str:
    """Where each language's guidance is, and what it covers."""
    where = "; ".join(f"{LANGUAGE_NAMES[name]}, on {LANGUAGE_RISKS[name][0]}, at {skill_path(name)}" for name in languages)
    return f"occam has guidance for {where}, if it would help."


def in_project(cwd: str | None) -> list[str]:
    """The languages the project's own files declare, in the working folder or the project root."""
    folders = [folder for folder in (cwd or os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR")) if folder]
    return [name for name, markers in LANGUAGE_MARKERS.items() if any(os.path.exists(os.path.join(folder, marker)) for folder in folders for marker in markers)]


def for_review(prompt: str, cwd: str | None) -> list[str]:
    """The languages a request names, by name, a tool only it uses or a quoted file's suffix, and then the project's. A wrong match
    adds a pointer rather than replacing the right one."""
    asked = re.sub(r"```.*?```", " ", scale_notes.without_pasted(prompt), flags=re.S)
    return list(dict.fromkeys([name for name, pattern in LANGUAGE_PROMPTS.items() if pattern.search(asked)] + in_project(cwd)))
