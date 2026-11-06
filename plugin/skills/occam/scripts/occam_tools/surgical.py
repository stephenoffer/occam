"""Did this change stay in scope? What only the diff can show: formatting churn, comments lost, code left orphaned, and handlers or comments far denser than the file around them.

These are questions for the author, not defects, since an agent asked to clean up may do all of them on purpose. They must still be true, so they lean on the
syntax tree and the source reader, and say nothing where neither can tell. Meaning is never inferred from text that merely looks alike.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from . import files as filesystem
from .source import C_FAMILY, Source, is_test_path, language_of, load

_HANDLERS = {"python": re.compile(r"^\s*except\b")}
_HANDLERS.update(dict.fromkeys(("javascript", "typescript", "java", "kotlin", "scala", "csharp", "php", "swift", "dart"), re.compile(r"\bcatch\b")))
_DEFERRED = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b|^\W*(?i:shortcut|todo|fixme):")
_COMMENT_EDGES = re.compile(r"^[\s#/*;<!-]+|[\s*/>-]+$")
_OWN_NAME = re.compile(r"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+\w+")
_ASSIGNED_OR_KEYWORD = re.compile(r"\b\w+\s*=(?!=)")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_ORPHAN_MODULE = re.compile(r"^Nothing imports or names (\w+)\.")
_CONFIG_FILES = ("pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "Makefile", "Procfile", "package.json")
MIN_FORMAT_LINES = 3
MIN_FILE_LINES = 30
MIN_ADDED_LINES = 8
MIN_NAME = 3  # identifiers() doesn't count anything shorter, so such names can't be judged


def _scope_note(rule: str, path: str, line: int, message: str) -> dict:
    return {"rule": rule, "path": path, "line": max(line, 1), "message": message, "category": "scope"}


class _Versions:
    """Each changed file before and after, read once."""

    def __init__(self, root: Path, revision: str) -> None:
        self.root, self.revision = root, revision
        self.cache: dict[tuple, Source | None] = {}

    def _load(self, path: str, text: str | None) -> Source | None:
        return load(path, text) if text is not None and language_of(path) else None

    def old(self, path: str) -> Source | None:
        key = ("old", path)
        if key not in self.cache:
            self.cache[key] = self._load(path, filesystem.file_at(self.root, self.revision, path))
        return self.cache[key]

    def new(self, path: str) -> Source | None:
        key = ("new", path)
        if key not in self.cache:
            self.cache[key] = self._load(path, filesystem.read_text(self.root / path))
        return self.cache[key]


def _without_comments(source: Source) -> list[str]:
    """Each line with any comment taken out. Text inside strings stays, because it isn't a comment."""
    lines = source.text.split("\n")
    for line, chunk in source.comments:
        for offset, part in enumerate(chunk.split("\n")):
            index = line - 1 + offset
            if index < len(lines):
                lines[index] = lines[index].replace(part, "", 1)
    return lines


# ---------------------------------------------------------------- formatting

def _statement_text(source: Source, tree: ast.Module) -> dict[str, list[str]]:
    code = source.code.split("\n")
    by_shape: dict[str, list[str]] = {}
    for node in tree.body:
        by_shape.setdefault(ast.dump(node), []).append("\n".join(line.rstrip() for line in code[node.lineno - 1:node.end_lineno]))
    return by_shape


def _python_layout_lines(old: Source, new: Source) -> tuple[int, int]:
    """(lines reformatted, first line), from top-level statements whose syntax tree is unchanged and whose layout isn't. Equal trees are the proof, so a real change can't count."""
    try:
        old_tree, new_tree = ast.parse(old.text), ast.parse(new.text)
    except (SyntaxError, ValueError):
        return 0, 0
    before = _statement_text(old, old_tree)
    code = new.code.split("\n")
    count = first = 0
    for node in new_tree.body:
        earlier = before.get(ast.dump(node))
        text = "\n".join(line.rstrip() for line in code[node.lineno - 1:node.end_lineno])
        if earlier and text not in earlier:
            count += max(node.end_lineno - node.lineno + 1, max(chunk.count("\n") + 1 for chunk in earlier))
            first = first or node.lineno
    return count, first


def _braced_layout_lines(path: str, hunks: list, new: Source) -> tuple[int, int]:
    """Lines whose only change is indentation, in languages where that means nothing. A line holding no code may sit inside a template literal, where it would."""
    code = new.code.split("\n")
    count = first = 0
    for _, _, _, line, removed, added in hunks:
        same = len(removed) == len(added) and all(a.strip() == b.strip() and "�" not in a + b for a, b in zip(removed, added))
        if same and removed != added and all(index < len(code) and code[index].strip() for index in range(line - 1, line - 1 + len(added))):
            count += len(added)
            first = first or line
    return count, first


def _format_churn(by_path: dict, versions: _Versions) -> list[dict]:
    notes = []
    for path, hunks in by_path.items():
        language, old, new = language_of(path), versions.old(hunks[0][1]), versions.new(path)
        if old is None or new is None:
            continue
        if language == "python":
            count, first = _python_layout_lines(old, new)
        elif language in C_FAMILY:
            count, first = _braced_layout_lines(path, hunks, new)
        else:
            continue
        if count >= MIN_FORMAT_LINES:
            notes.append(_scope_note("format-only", path, first, f"{count} changed lines differ only in formatting. Leave formatting out unless the request asked for it."))
    return notes


# ---------------------------------------------------------------- comments

def _comment_text(source: Source) -> list[tuple[int, str]]:
    """(line, comment with its punctuation and spacing gone), so `#foo` and `# foo` are one comment. Line 1 of a script may be a shebang, which isn't one."""
    found = []
    for line, chunk in source.comments:
        for offset, part in enumerate(chunk.split("\n")):
            if line + offset == 1 and part.startswith("#!"):
                continue
            text = " ".join(_COMMENT_EDGES.sub("", part).split())
            if text:
                found.append((line + offset, text))
    return found


def _span(lines: list[str], start: int, count: int) -> list[str]:
    """`count` lines from 1-based `start`. A hunk with nothing on one side names the line before it, which is 0 at the top of a file."""
    return lines[start - 1:start - 1 + count] if count else []


def _code_unchanged(hunk: tuple, old_lines: list[str], new_lines: list[str]) -> bool:
    _, _, old_start, new_start, removed, added = hunk
    return [text.strip() for text in _span(old_lines, old_start, len(removed)) if text.strip()] == [text.strip() for text in _span(new_lines, new_start, len(added)) if text.strip()]


def _comments_lost_in(hunks: list, old: Source, new: Source) -> tuple[int, int]:
    """Comments the file no longer has anywhere, in hunks that change no code. A comment that moved is still there, and one that goes with its code wasn't the side effect this looks for."""
    gone = Counter(text for _, text in _comment_text(old)) - Counter(text for _, text in _comment_text(new))
    old_lines, new_lines = _without_comments(old), _without_comments(new)
    count = first = 0
    for line, text in _comment_text(old):
        if gone[text] <= 0 or _DEFERRED.search(text):
            continue
        hunk = next((h for h in hunks if h[2] <= line < h[2] + len(h[4])), None)
        if hunk and _code_unchanged(hunk, old_lines, new_lines):
            gone[text] -= 1
            count += 1
            first = first or hunk[3]
    return count, first


def _comments_lost(by_path: dict, versions: _Versions) -> list[dict]:
    notes = []
    for path, hunks in by_path.items():
        old, new = versions.old(hunks[0][1]), versions.new(path)
        count, first = _comments_lost_in(hunks, old, new) if old is not None and new is not None else (0, 0)
        if count:
            notes.append(_scope_note("comment-removed", path, first, f"{count} existing comments removed or reworded with no code change beside them. Keep them unless this change made them false or the request asked."))
    return notes


# ---------------------------------------------------------------- orphans

def _removed_code(hunks: list, versions: _Versions) -> list[str]:
    """Code lines this change removed, read from the old file so that comments and string contents are gone."""
    lines: list[str] = []
    for _, old_path, old_start, _, removed, _ in hunks:
        old = versions.old(old_path) if removed else None
        if old is not None:
            lines += _span(old.code.split("\n"), old_start, len(removed))
    return lines


def _references_in(lines: list[str]) -> set[str]:
    """Names these lines used. A definition's own name and the left of an `=`, including a keyword argument, aren't uses of it."""
    names: set[str] = set()
    for line in lines:
        names.update(_IDENTIFIER.findall(_ASSIGNED_OR_KEYWORD.sub(" ", _OWN_NAME.sub(" ", line))))
    return names


def _named_in_config(root: Path, name: str) -> bool:
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    return any(pattern.search(filesystem.read_text(root / config) or "") for config in _CONFIG_FILES if (root / config).is_file())


def _lost_definitions(project, references: set[str]) -> list[tuple[str, int, str]]:
    found = []
    for path, facts in project.facts.items():
        exports = set(facts.get("exports") or [])
        for item in [*facts.get("defs", []), *facts.get("classes", [])]:
            name = item["name"]
            if (name in references and len(name) >= MIN_NAME and project.identifier_counts.get(name, 0) <= 1 and not item.get("decorated")
                    and not is_test_path(path) and name not in exports and not name.startswith("__") and name not in ("main", "cli")):
                found.append((path, item["line"], name))
    return found


def _orphans(root: Path, hunks: list, project, findings: list[dict], versions: _Versions) -> list[dict]:
    """Definitions with no references left, where this change removed one. Those are this change's to remove, wherever they live. Dead code that was already dead is not."""
    removed = _removed_code(hunks, versions)
    lost = _lost_definitions(project, _references_in(removed))
    imports = [line for line in removed if re.match(r"\s*(?:from|import)\b", line)]
    for finding in findings:
        match = _ORPHAN_MODULE.match(finding["message"]) if finding["rule"] == "orphan-module" else None
        if match and len(match.group(1)) >= MIN_NAME and any(re.search(rf"\b{re.escape(match.group(1))}\b", line) for line in imports):
            lost.append((finding["path"], finding["line"], match.group(1)))
    return [_scope_note("orphaned-by-change", path, line, f"{name} has no references left, and this change removed one. Remove it if nothing outside the code read here needs it.")
            for path, line, name in lost if not _named_in_config(root, name)]


# ---------------------------------------------------------------- denser than the file

def _comment_density(path: str, line: int, added: list[int], source: Source, old: Source) -> list[dict]:
    def is_comment(lines: list[str], text: list[str], index: int) -> bool:
        return index < len(lines) and bool(text[index].strip()) and not lines[index].strip()

    new_plain, new_text = _without_comments(source), source.text.split("\n")
    old_plain, old_text = _without_comments(old), old.text.split("\n")
    new_count = sum(is_comment(new_plain, new_text, index) for index in added)
    old_count = sum(is_comment(old_plain, old_text, index) for index in range(len(old_text)))
    new_rate, old_rate = new_count / len(added), old_count / max(sum(1 for text in old_text if text.strip()), 1)
    if new_count >= 3 and new_rate >= 0.25 and new_rate >= 3 * old_rate:
        return [_scope_note("comment-density", path, line, f"{new_rate:.0%} of the added lines are comments, against {old_rate:.0%} in this file. Keep only what the code can't say.")]
    return []


def _handler_density(path: str, line: int, added: list[int], source: Source, old: Source, pattern: re.Pattern) -> list[dict]:
    code, old_code = source.code.split("\n"), old.code.split("\n")
    new_count = sum(1 for index in added if index < len(code) and pattern.search(code[index]))
    old_count = sum(1 for text in old_code if pattern.search(text))
    old_size = max(sum(1 for text in old.text.split("\n") if text.strip()), 1)
    if new_count >= 2 and new_count / len(added) >= 0.05 and new_count / len(added) >= 3 * old_count / old_size:
        return [_scope_note("handler-density", path, line, f"{new_count} exception handlers in {len(added)} added lines, against {old_count} in the {old_size} lines here. Each should name a failure that can happen.")]
    return []


def _denser_than_the_file(by_path: dict, versions: _Versions) -> list[dict]:
    """What counts as excess depends on the file. New code far heavier in comments or handlers than the code around it is worth a second look."""
    notes: list[dict] = []
    for path, hunks in by_path.items():
        new, old = versions.new(path), versions.old(hunks[0][1])
        if new is None or old is None or is_test_path(path):
            continue
        text = new.text.split("\n")
        added = [index for hunk in hunks for index in range(hunk[3] - 1, hunk[3] - 1 + len(hunk[5])) if index < len(text) and text[index].strip()]
        if len(added) < MIN_ADDED_LINES or sum(1 for line in old.text.split("\n") if line.strip()) < MIN_FILE_LINES:
            continue
        notes += _comment_density(path, hunks[0][3], added, new, old)
        handlers = _HANDLERS.get(new.language)
        if handlers:
            notes += _handler_density(path, hunks[0][3], added, new, old, handlers)
    return notes


# ---------------------------------------------------------------- size

def _size_line(root: Path, hunks: list, analyzed: set[str], changed: dict) -> str:
    """Only what the scanner read, or a code file this change deleted. A notebook's lines are JSON, so they say nothing about how much code changed."""
    totals = {"source": [0, 0], "tests": [0, 0]}
    for path, _, _, _, removed, added in hunks:
        deleted = language_of(path) and not (root / path).exists()
        if (path in analyzed or deleted) and language_of(path) != "notebook":
            bucket = totals["tests" if is_test_path(path) else "source"]
            bucket[0] += len(added)
            bucket[1] += len(removed)
    for name in (filesystem.run_git(root, "ls-files", "-o", "--exclude-standard", "-z") or "").split("\0"):
        if name in changed and name in analyzed and language_of(name) != "notebook":
            text = filesystem.read_text(root / name)
            totals["tests" if is_test_path(name) else "source"][0] += len(text.splitlines()) if text else 0
    (source_added, source_removed), (tests_added, tests_removed) = totals["source"], totals["tests"]
    if not any((source_added, source_removed, tests_added, tests_removed)):
        return ""
    return f"Size: +{source_added} -{source_removed} lines of source, +{tests_added} -{tests_removed} of tests."


def review(root: Path, base: str | None, changed: dict, result) -> dict | None:
    """Scope notes and the size of this change, or None if the diff can't be read."""
    hunks = filesystem.diff_hunks(root, base)
    if hunks is None:
        return None
    analyzed = {path for path, language in result.project.languages.items() if language} - set(result.stats["unscanned"]) - set(result.stats["generated"])
    by_path: dict[str, list] = {}
    for hunk in hunks:
        if hunk[0] in changed and hunk[0] in analyzed:
            by_path.setdefault(hunk[0], []).append(hunk)
    versions = _Versions(root, base or "HEAD")
    notes = [*_format_churn(by_path, versions), *_comments_lost(by_path, versions), *_orphans(root, hunks, result.project, result.findings, versions), *_denser_than_the_file(by_path, versions)]
    return {"notes": notes, "size": _size_line(root, hunks, analyzed, changed)}
