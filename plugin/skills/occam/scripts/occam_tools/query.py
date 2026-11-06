"""Plain answers about a repository, where `scan` gives judgments.

What every query shares: which files count, a search that stays fast on a huge repository, and what a matched position is.
A query reads, runs nothing from the repository, bounds what it prints, and says what it couldn't see.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path
from typing import Callable, NamedTuple

from . import files as filesystem
from .rules_text import _NOT_A_SECRET, _SECRET_DEFAULT, _SECRET_TOKENS
from .source import Source, language_of, load, reads_comments

MAX_HITS = 200_000  # beyond this a search says it stopped, rather than hold the whole repository in memory
MAX_LINE = 160
MAX_FILES_KEPT = 64
MAX_LINE_READ = 4000  # past this a line is data, and an expression tried at every position on one could take minutes
_NAME = r"(?:pass(?:word|wd|phrase)|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)"
_QUOTED_CREDENTIAL = re.compile(rf"""{_NAME}[\w.-]*["']?[ \t]*(?::[ \t]*[\w\[\], .|]+?[ \t]*)?(?::=|=>|=|:)[ \t]*f?(?:"([^"\n]+)"|'([^'\n]+)')""", re.I)
_BARE_CREDENTIAL = re.compile(rf"""{_NAME}[\w.-]*["']?[ \t]*(?::=|=>|=|:)[ \t]*([^\s"'(){{}}\[\],;$<>]+)[ \t]*(?:\#.*)?$""", re.I)
_URL_PASSWORD = re.compile(r"://[^/\s:@]{1,200}:([^@/\s]{1,200})@")
_KEY_BODY = re.compile(r"^[ \t]*[A-Za-z0-9+/]{40,}={0,2}[ \t]*$")  # a line of a PEM block, whose header is usually on another line
# A word boundary that means the same to git's POSIX expressions on every platform and to Python's.
WORD_START = r"(^|[^A-Za-z0-9_])"
WORD_END = r"([^A-Za-z0-9_]|$)"


class BadQuestion(ValueError):
    """A query that can't be answered as asked, where an empty answer would look like a clean one."""


class Hit(NamedTuple):
    path: str
    line: int
    text: str


def render(data: dict, renderer: Callable[[dict], str], form: str) -> str:
    return json.dumps(data, indent=2) if form == "json" else renderer(data)


def selected_files(root: Path, targets: list[str] | None) -> list[str]:
    if filesystem.in_git(root) and filesystem.tracked_files(root) is None:
        raise filesystem.GitProblem("git can't list this repository's files")  # falling back to a walk would answer for a different set of files
    return filesystem.list_files(root, targets or None, filesystem.load_config(root))


def left_out_note(root: Path) -> str:
    """What an empty answer can't speak for."""
    ignored = filesystem.load_config(root).get("ignore", [])
    submodules = filesystem.submodule_paths(root) if filesystem.in_git(root) else []
    return ("Folders named vendor, dist, build or target are left out unless you name one." + (f" This repository's .occam.json also leaves out {', '.join(ignored[:6])}." if ignored else "")
            + (f" Submodules aren't entered: {', '.join(submodules[:6])}." if submodules else ""))


def missing_paths(paths: list[str] | None) -> list[str]:
    return [path for path in paths or [] if not Path(path).exists()]


def language_at(root: Path, path: str) -> str | None:
    """By extension, then by a shebang for the files that have none."""
    language = language_of(path)
    if language or "." in path.rsplit("/", 1)[-1]:
        return language
    if not filesystem.is_plain_file(root / path):
        return None
    try:
        with open(root / path, "rb") as handle:
            return language_of(path, handle.read(200).decode("utf-8", "replace"))
    except OSError:
        return None


def _looks_random(value: str) -> bool:
    """A bare value that reads like a key rather than a variable name. `token = new_token` is code."""
    return any(character.isdigit() for character in value) or (value.lower() != value and value.upper() != value) or any(character in value for character in "+/=")


def credential_in(line: str) -> tuple[str, str] | None:
    """(how sure, value) if a line carries a credential: `shape` for what's unmistakable, `named` for a value assigned to a credential's name.

    The scanner's own check drops placeholders so its findings stay worth reading. Output needs the opposite bias, so this keeps them, and `leaks` filters them itself.
    """
    line = line[:MAX_LINE_READ]
    for pattern, kind in ((_SECRET_TOKENS, "shape"), (_URL_PASSWORD, "shape"), (_KEY_BODY, "shape")):
        match = pattern.search(line)
        if match:
            return kind, match.group(0)
    match = _QUOTED_CREDENTIAL.search(line) or _SECRET_DEFAULT.search(line)
    if match:
        return "named", next(group for group in match.groups() if group)
    match = _BARE_CREDENTIAL.search(line)
    return ("named", match.group(1)) if match and _looks_random(match.group(1)) else None


def worth_reporting(found: tuple[str, str]) -> bool:
    """Whether `leaks` should report it, since `password = "changeme"` is withheld from output but is no leak."""
    return found[0] == "shape" or not _NOT_A_SECRET.search(found[1])


def safe_line(text: str) -> str:
    """A matched line, short, with anything shaped like a credential kept out of the output."""
    stripped = text.strip()
    if credential_in(stripped):
        return "(line withheld: it looks like a credential)"
    return stripped[:MAX_LINE] + ("..." if len(stripped) > MAX_LINE else "")


def shown(items: list, top: int) -> tuple[list, int]:
    """The first `top` items, and how many that left out."""
    return items[:top], max(0, len(items) - top)


def more(left_out: int, flag: str = "--top") -> list[str]:
    return [f"  ... and {left_out:,} more. Raise {flag} to see them."] if left_out else []


def relative_path(root: Path, target: str) -> str:
    try:
        return str(Path(target).resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError as error:
        raise filesystem.OutsideProject(f"{target} is outside this project ({root}). Nothing was checked.") from error


def _pathspecs(root: Path, targets: list[str] | None) -> list[str]:
    specs = []
    for target in targets or []:
        relative = relative_path(root, target)
        if relative == ".":
            return []
        specs.append(f":(literal){relative}")
    return ["--", *specs] if specs else []


def _is_text(path: Path) -> bool:
    if not filesystem.is_plain_file(path):
        return False
    try:
        with open(path, "rb") as handle:
            return b"\0" not in handle.read(8000)
    except OSError:
        return False


def _git_hits(root: Path, patterns: list[str], targets, fixed: bool, word: bool, ignore_case: bool) -> Iterator[Hit]:
    """-a and our own check for binaries, because a repository's `* -diff` makes -I skip every file. Settings that change the output's shape are pinned."""
    args = ["-c", "grep.column=false", "-c", "grep.fullName=false", "-c", "grep.fallbackToNoIndex=false", "grep", "-a", "-n", "--null", "--no-color", "--untracked", "-F" if fixed else "-E"]
    args += ["-w"] if word else []
    args += ["-i"] if ignore_case else []
    args += ["--no-exclude-standard"] if targets else []  # naming a file is a request to read it. What wasn't named is filtered out below
    for pattern in patterns:
        args += ["-e", pattern]
    text_files: dict[str, bool] = {}
    pending = ""
    for line in filesystem.stream_git(root, *args, *_pathspecs(root, targets), ok_codes=(0, 1)):
        if "\0" not in line:  # a newline in a file name splits its record
            pending += line + "\n"
            continue
        parts = (pending + line).split("\0", 2)
        pending = ""
        if len(parts) == 3 and parts[1].isdigit():
            if parts[0] not in text_files:
                text_files[parts[0]] = _is_text(root / parts[0])
            if text_files[parts[0]]:
                yield Hit(parts[0], int(parts[1]), parts[2][:MAX_LINE_READ])


def _walk_hits(root: Path, files: list[str], patterns: list[str], fixed: bool, word: bool, ignore_case: bool) -> Iterator[Hit]:
    """The same search for a folder that isn't a git repository."""
    expression = "|".join(re.escape(pattern) if fixed else pattern for pattern in patterns)
    expression = rf"(?<![A-Za-z0-9_])(?:{expression})(?![A-Za-z0-9_])" if word else expression
    compiled = re.compile(expression, re.I if ignore_case else 0)
    for path in files:
        text = filesystem.read_text(root / path)
        if text is None:
            continue
        for number, line in enumerate(text.split("\n"), start=1):
            if compiled.search(line[:MAX_LINE_READ]):
                yield Hit(path, number, line[:MAX_LINE_READ])


def search(root: Path, pattern: str | list[str], targets: list[str] | None = None, fixed: bool = False, word: bool = False, ignore_case: bool = False,
           limit: int = MAX_HITS, only: Callable[[str], bool] | None = None) -> tuple[list[Hit], bool]:
    """Lines matching a POSIX extended expression, or any of several, in the files that count. The bool says it stopped at the limit.

    git grep reads a 4 million line repository in under a second, where parsing it takes over a minute, so anything that can start from text does.
    A long alternation is what slows it down, so many names should come as a list of fixed strings.
    """
    files = selected_files(root, targets)
    allowed = {path for path in files if only is None or only(path)}  # filtered before the limit, so other files' hits can't use it up
    patterns = [pattern] if isinstance(pattern, str) else pattern
    source = _git_hits(root, patterns, targets, fixed, word, ignore_case) if filesystem.in_git(root) else _walk_hits(root, files, patterns, fixed, word, ignore_case)
    hits = []
    stopped = False
    for hit in source:
        if hit.path in allowed:
            hits.append(hit)
            if len(hits) >= limit:
                source.close()
                stopped = True
                break
    hits.sort()  # the two engines list files in different orders, and an answer shouldn't depend on which one ran
    return hits, stopped


class Views:
    """What each position is, code, comment, string or plain text. Only files a search hit get loaded, and only the most recent are kept,
    since one query can touch every file in a giant repository. Going through hits file by file means nothing loads twice."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._sources: OrderedDict[str, Source | None] = OrderedDict()
        self._comment_lines: dict[str, set[int]] = {}

    def source(self, path: str) -> Source | None:
        if path in self._sources:
            self._sources.move_to_end(path)
            return self._sources[path]
        text = filesystem.read_text(self.root / path)
        language = language_at(self.root, path)
        found = load(path, text, language) if text is not None and language else None
        self._sources[path] = found
        self._comment_lines[path] = {line + extra for line, chunk in found.comments for extra in range(chunk.count("\n") + 1)} if found else set()
        if len(self._sources) > MAX_FILES_KEPT:
            oldest, _ = self._sources.popitem(last=False)
            del self._comment_lines[oldest]
        return found

    def kind_of(self, hit: Hit, match: re.Match) -> str:
        """What a match on a hit's line starts in. A match can begin with the space before a word, which says nothing, so that's skipped."""
        found = match.group(0)
        return self.kind_at(hit.path, hit.line, match.start() + len(found) - len(found.lstrip()))

    def kind_at(self, path: str, line: int, column: int) -> str:
        """code, comment or string, or text for a file with no such distinction."""
        source = self.source(path)
        if source is None and language_at(self.root, path):
            return "code"  # too large to load, and hiding a hit is worse than not knowing what it's inside
        if source is None or not reads_comments(source.language):
            return "text"
        code = line_of(source.code, source, line)
        raw = line_of(source.text, source, line)
        if column < len(code) and column < len(raw) and code[column] == raw[column] and not raw[column].isspace():
            return "code"
        return "comment" if line in self._comment_lines[path] else "string"


def hits_by_file(searches: list[tuple]) -> tuple[list[tuple], bool]:
    """Hits from several searches as (hit, tag, compiled expression), in file order. The bool says any search stopped at its limit."""
    rows = []
    stopped = False
    for tag, pattern, hits, limited in searches:
        compiled = re.compile(pattern)
        stopped = stopped or limited
        rows += [(hit, tag, compiled) for hit in hits]
    rows.sort(key=lambda row: row[0].path)
    return rows, stopped


def line_of(view: str, source: Source, number: int) -> str:
    """Views keep every offset, so one table of line starts serves them all."""
    starts = source.line_starts
    if not 1 <= number <= len(starts):
        return ""
    end = starts[number] - 1 if number < len(starts) else len(view)
    return view[starts[number - 1]:end]


def enclosing(defs: list[dict], line: int) -> str | None:
    """The innermost function around a line, from the (line, end) of each definition."""
    best = None
    for definition in defs:
        if definition.get("line", 0) <= line <= (definition.get("end") or 0):
            if best is None or definition["line"] >= best["line"]:
                best = definition
    if best is None:
        return None
    return f"{best['class']}.{best['name']}" if best.get("class") else best["name"]
