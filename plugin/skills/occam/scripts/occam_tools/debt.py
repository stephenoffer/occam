"""Work the code says it deferred: marked shortcuts and TODO-style notes, as one list, so nothing is put off without a record."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from . import files as filesystem
from .rules_text import SHORTCUT_MARK, states_when_due
from .source import language_of, load, looks_generated, reads_comments

MAX_ROWS = 100
MAX_CONTINUATION = 3
_WORD = r"TODO|FIXME|HACK|XXX"
_OWNER = r"(?P<owner>\([^)\n]*\))?"
# A note starts a comment or follows a sentence. "TODO list", "TODO.md" and "we grep for TODO:" only mention one.
_AT_START = re.compile(rf"^\W*(?P<word>{_WORD})(?!\.\w)\b(?!\s+(?:lists?|comments?|week|items?|files?|markers?|counts?)\b){_OWNER}")
_ANY_CASE = re.compile(rf"^\W*(?P<word>(?i:todo|fixme|hack|xxx)){_OWNER}:")
_COMMENT_CLOSE = re.compile(r"\s*(?:\*/|-->)\s*$")
_AFTER_SENTENCE = re.compile(rf"[.;]\s+(?P<word>{_WORD}){_OWNER}:")


def _marker(line: str) -> tuple[str, str] | None:
    """(kind, text after the marker) if this comment line is deferred work."""
    shortcut = SHORTCUT_MARK.search(line)
    if shortcut:
        return "shortcut", line[shortcut.end():].strip()
    line = _COMMENT_CLOSE.sub("", line)
    note = _AT_START.search(line) or _ANY_CASE.search(line) or _AFTER_SENTENCE.search(line)
    if not note:
        return None
    return note.group("word").upper(), f"{note.group('owner') or ''} {line[note.end():].lstrip(' :-')}".strip()


def _comment_lines(path: str, text: str) -> dict[int, str]:
    lines: dict[int, str] = {}
    for number, comment in load(path, text).comments:
        for offset, part in enumerate(comment.splitlines()):
            lines[number + offset] = part
    return lines


def _rows(path: str, text: str) -> list[dict]:
    lines = _comment_lines(path, text)
    rows = []
    for number, line in lines.items():
        found = _marker(line)
        if not found:
            continue
        kind, note = found
        for following in range(number + 1, number + 1 + MAX_CONTINUATION):  # a note can wrap, and its trigger is often on the next line
            if following not in lines or _marker(lines[following]):
                break
            note = f"{note} {lines[following].strip(' #/*-')}".strip()
        rows.append({"path": path, "line": number, "kind": kind, "text": note[:160], "trigger": states_when_due(note)})
    return rows


def _collect(root: Path, paths: list[str] | None) -> tuple[list[dict], int, set[str]]:
    rows: list[dict] = []
    notebooks = 0
    unreadable: set[str] = set()
    for path in filesystem.list_files(root, paths, filesystem.load_config(root)):
        language = language_of(path)
        if language == "notebook":
            notebooks += 1
        elif language or not PurePosixPath(path).suffix:  # a script with no extension says what it is on its first line
            text = filesystem.read_text(root / path)
            language = language or language_of(path, (text or "")[:200])
            if language and not reads_comments(language):
                unreadable.add(language)
            elif language and text is not None and not looks_generated(text):
                rows += _rows(path, text)
    return rows, notebooks, unreadable


def _listing(rows: list[dict]) -> list[str]:
    lacking = sum(1 for row in rows if not row["trigger"])
    lines = [f"occam debt: {len(rows)} markers in {len({row['path'] for row in rows})} files, {lacking} with no trigger to revisit them.", ""]
    current = None
    for row in rows[:MAX_ROWS]:
        if row["path"] != current:
            current = row["path"]
            lines.append(current)
        lines.append(f"  {row['line']:>5}  {row['kind']:<8}  {row['text']}{'' if row['trigger'] else '  [no trigger]'}")
    if len(rows) > MAX_ROWS:
        lines.append(f"... and {len(rows) - MAX_ROWS} more.")
    return [*lines, "", "Convention: `shortcut: <the limit>, <when to revisit>`. A limit with a stated way out may be deliberate, but a comment can't excuse a security or data defect, so weigh it yourself.",
            "[no trigger] means this doesn't appear to say when it comes due. Add the condition or do the work. Telling that from wording is a guess, so read them."]


def debt(root: Path, paths: list[str] | None = None) -> str:
    rows, notebooks, unreadable = _collect(root, paths)
    lines = _listing(rows) if rows else ["No deferred work marked in comments this could read."]
    if notebooks:
        lines += ["", f"NOT CHECKED: {notebooks} notebooks."]
    if unreadable:
        lines += ["", f"NOT CHECKED: comments in {', '.join(sorted(unreadable))}, which this can't read."]
    return "\n".join(lines)
