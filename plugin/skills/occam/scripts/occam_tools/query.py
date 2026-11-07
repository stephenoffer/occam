"""Plain answers about a repository, where `scan` gives judgments.

What every query shares: which files count, a search that stays fast on a huge repository, and what a matched position is.
A query reads, runs nothing from the repository, bounds what it prints, and says what it couldn't see.
"""

from __future__ import annotations

import os
import re
from collections import Counter, OrderedDict
from collections.abc import Iterator
from pathlib import Path
from typing import Callable, NamedTuple

from . import files as filesystem
from .rules_text import _SECRET_DEFAULT, _SECRET_TOKENS
from .source import Source, language_of, load, reads_comments

MAX_HITS = 200_000  # beyond this a search says it stopped, rather than hold the whole repository in memory
MAX_LINE = 160
MAX_FILES_KEPT = 64
MAX_LINE_READ = 4000  # expressions read a line in pieces of this, since one tried at every position of a long line could take minutes
MAX_LINE_SCANNED = 1_000_000  # a minified bundle can hold a credential far along, and past this a line is data
MAX_LEFT_OUT_FILES = 5000  # outside git, how many left-out files get searched for what an empty answer would otherwise miss
MAX_LEFT_OUT_HITS = 200
_NEVER_CALLERS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "site-packages", "bower_components", ".tox", ".nox", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".cache"}
_BLANKS = re.compile(r"[ \t]{2,}")
_NAME = r"(?:pass(?:word|wd|phrase)|pass(?![a-z])|pwd|secret|token(?!iz)|api[_-]?key|access[_-]?key|private[_-]?key|credential)"
_MORE_TOKENS = re.compile(r"\b(?:[sr]k_live_[A-Za-z0-9]{16,}|glpat-[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]{20,}|ASIA[0-9A-Z]{16}|npm_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}|pypi-[A-Za-z0-9_-]{30,})\b")
_KEY_BODY = re.compile(r"^[ \t]*[A-Za-z0-9+/]{40,}={0,2}[ \t\r]*$")  # a line of a PEM block, whose header is usually on another line
_QUOTED_CREDENTIAL = re.compile(rf"""{_NAME}[\w.-]{{0,80}}["']?[ \t]*(?::[ \t]*[\w\[\], .|]{{1,80}}?[ \t]*)?(?::=|=>|!=|={{1,3}}|:)[ \t]*[a-zA-Z]{{0,2}}(?:"([^"\n]+)"|'([^'\n]+)')""", re.I)
_CALL_CREDENTIAL = re.compile(rf"""{_NAME}\w{{0,80}}\([ \t]*[a-zA-Z]{{0,2}}["']([^"'\n]{{4,}})["']""", re.I)
_FLAG_CREDENTIAL = re.compile(rf"""--[\w-]{{0,80}}{_NAME}[\w-]{{0,80}}[ \t]+([^\s$-]\S*)""", re.I)
_ENV_CREDENTIAL = re.compile(r"""(?:^|[\s;&])(?:export[ \t]+)?[A-Z0-9_]{0,80}(?:PASS|SECRET|TOKEN|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIAL|PWD)[A-Z0-9_]{0,80}=([^\s"'$`{(][^\s"']*)""")
_BARE_CREDENTIAL = re.compile(rf"""{_NAME}[\w.-]{{0,80}}["']?[ \t]*(?::=|=>|=(?!=)|:)[ \t]*([^\s"'(){{}}\[\],;<>$][^\s"'(){{}}\[\],;<>]*)(?:["'\])}},;\s]|$)""", re.I)
_URL_PASSWORD = re.compile(r"://[^/\s:@]{0,200}:([^@/\s]{1,200})@|://([A-Za-z0-9_-]{12,200})@")
_BEARER = re.compile(r"\b(?:bearer|basic)[ \t]+([A-Za-z0-9._~+/=-]{12,})", re.I)
_DOTTED_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_PLACEHOLDER = re.compile(r"changeme|change_me|example|your|xxx|placeholder|dummy|fake|sample|redacted|\*\*\*|^(?:test|secret|password|passwd|pass|none|null|true|false|token|key|admin|root|foo|bar|baz)$|^[$%<{]|^[a-z]+[_.-][a-z_.-]+$", re.I)
# A word boundary that means the same to git's POSIX expressions on every platform and to Python's.
WORD_START = r"(^|[^A-Za-z0-9_])"
WORD_END = r"([^A-Za-z0-9_]|$)"


def config_ignores(root: Path) -> list[str]:
    return filesystem.load_config(root).get("ignore", [])


class BadQuestion(ValueError):
    """A query that can't be answered as asked, where an empty answer would look like a clean one."""


class Hit(NamedTuple):
    path: str
    line: int
    text: str


def selected_files(root: Path, targets: list[str] | None) -> list[str]:
    if filesystem.in_git(root) and filesystem.tracked_files(root) is None:
        raise filesystem.GitProblem("git can't list this repository's files")  # falling back to a walk would answer for a different set of files
    return filesystem.list_files(root, targets or None, filesystem.load_config(root))


def left_out_note(root: Path) -> str:
    """What an empty answer can't speak for. What .occam.json leaves out is said once, by `cmd_query`, for every query."""
    submodules = filesystem.submodule_paths(root) if filesystem.in_git(root) else []
    return "Folders named vendor, dist, build or target are left out unless you name one." + (f" Submodules aren't entered: {', '.join(submodules[:6])}." if submodules else "")


def rust_use_trees(code: str, head: re.Pattern) -> list[tuple[int, str]]:
    """(offset, what's between each `use` and its semicolon), found with `find`, since an expression trying this at every `use` of a file with no semicolons would take minutes."""
    found = []
    for match in head.finditer(code):
        end = code.find(";", match.end(), match.end() + MAX_LINE_READ)
        if end >= 0:
            found.append((match.start(), code[match.end():end]))
    return found


def rust_use_paths(tree: str) -> list[tuple[list[str], str]]:
    """Each path in a `use` tree, as (its parts, the name it's visible by, or * for a glob): `crate::{b::thing, c::{self, other as o}}` is three."""
    found: list[tuple[list[str], str]] = []
    stack: list[list[str]] = []
    current: list[str] = []
    visible = ""

    def flush() -> None:
        pending = current[:-1] if current[-1:] == ["self"] and len(current) > 1 else current
        if pending and (not stack or current != stack[-1]):
            found.append((pending, visible or pending[-1]))

    for token in re.findall(r"[{},*]|\w+(?:\s+as\s+\w+)?", tree):
        if token == "{":
            stack.append(current)
            current = list(current)
        elif token == "*":
            visible = "*"
        elif token in (",", "}"):
            flush()
            visible = ""
            if token == "}" and stack:
                stack.pop()
            current = list(stack[-1]) if stack else []
        else:
            words = token.split()
            current = [*current, words[0]]
            visible = words[-1] if len(words) > 1 else ""
    if current or visible:
        flush()
    return found


def go_block_names(code: str, start: int) -> tuple[list[tuple[str, int, str]], int]:
    """(name, offset, what follows) in `const ( ... )` from just inside it, and where it ended. A nested struct or a multi-line value isn't a name of its own."""
    names, depth, position = [], 0, start
    while position < len(code):
        end = code.find("\n", position)
        end = len(code) if end < 0 else end
        line = code[position:end]
        stripped = line.strip()
        if depth == 0 and stripped.startswith(")"):
            return names, end
        if depth == 0:
            found = re.match(r"(\w+(?:[ \t]*,[ \t]*\w+)*)([^\n{=]*)", stripped)
            if found:
                names += [(name.strip(), position, found.group(2)) for name in found.group(1).split(",")]
        depth = max(0, depth + sum(line.count(c) for c in "({[") - sum(line.count(c) for c in ")}]"))
        position = end + 1
    return names, len(code)


def language_at(root: Path, path: str) -> str | None:
    """By extension, then by a shebang for the files that have none."""
    language = language_of(path)
    if language or "." in path.rsplit("/", 1)[-1]:
        return language
    if not filesystem.is_plain_file(root / path):
        return None
    try:
        with open(root / path, "rb") as handle:
            head = handle.read(200).decode("utf-8", "replace")
        return language_of(path, head)
    except OSError:
        return None


def _looks_random(value: str) -> bool:
    """A bare value that reads like a key rather than code. `token = new_token`, `max_tokens = 1024` and `api_key=settings.API_KEY` are code."""
    if len(value) < 6 or value.isdigit() or "://" in value or _DOTTED_NAME.fullmatch(value):
        return False
    return any(character.isdigit() or character in "+/!@#%^&*$" for character in value)


def credential_in(line: str) -> tuple[str, str] | None:
    """(how sure, value) if a line carries a credential: `shape` for what's unmistakable, `named` for a value that a name or a place suggests is one.

    The scanner's own check drops placeholders so its findings stay worth reading. Output needs the opposite bias, so this keeps them, and `leaks` filters them itself.
    It reads one line at a time and goes by shape and name, so a credential with neither still prints, such as `password: correcthorse` or the short last line of a key.
    """
    found = None
    for start in range(0, min(len(line), MAX_LINE_SCANNED) or 1, MAX_LINE_READ - 400):  # the overlap keeps a credential whole
        piece = _credential_in_piece(_BLANKS.sub(" ", line[start:start + MAX_LINE_READ]))
        if piece and worth_reporting(piece):
            return piece
        found = found or piece
        if start + MAX_LINE_READ >= len(line):
            break
    return found


def _credential_in_piece(line: str) -> tuple[str, str] | None:
    """Every value on a line, since a placeholder beside a real one mustn't speak for it. A placeholder alone still counts, for output's sake."""
    for pattern in (_SECRET_TOKENS, _MORE_TOKENS, _KEY_BODY):
        match = pattern.search(line)
        if match:
            return "shape", match.group(0)
    placeholder = None
    for pattern in (_URL_PASSWORD, _QUOTED_CREDENTIAL, _SECRET_DEFAULT, _CALL_CREDENTIAL, _FLAG_CREDENTIAL, _ENV_CREDENTIAL):
        for match in pattern.finditer(line):
            found = ("named", next(group for group in match.groups() if group))
            if worth_reporting(found):
                return found
            placeholder = placeholder or found
    for pattern in (_BARE_CREDENTIAL, _BEARER):
        for match in pattern.finditer(line):
            if _looks_random(match.group(1)):
                found = ("named", match.group(1))
                if worth_reporting(found):
                    return found
                placeholder = placeholder or found
    return placeholder


def worth_reporting(found: tuple[str, str]) -> bool:
    """Whether `leaks` should report it, since `password = "changeme"` is withheld from output but is no leak."""
    return found[0] == "shape" or not _PLACEHOLDER.search(found[1])


def safe_line(text: str) -> str:
    """A matched line, short, with anything shaped like a credential kept out of the output."""
    stripped = text.strip()
    if credential_in(stripped):
        return "(line withheld: it looks like a credential)"
    return stripped[:MAX_LINE] + ("..." if len(stripped) > MAX_LINE else "")


def printable(value):
    """Every string in an answer with control characters shown, not sent: a file name or a commit subject can hold a line break that forges a line, or codes for a terminal."""
    if isinstance(value, str):
        return _CONTROL.sub(lambda match: f"\\x{ord(match.group(0)):02x}", value)
    if isinstance(value, dict):
        return {printable(key): printable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(printable(item) for item in value)
    return value


def languages_outside(root: Path, targets: list[str] | None, known: set[str]) -> list[tuple[str, int]]:
    """Languages here, most files first, that a question's patterns weren't written for, since a low count there doesn't mean little was found."""
    counts = Counter(language_at(root, path) for path in selected_files(root, targets))
    return sorted(((name, count) for name, count in counts.items() if name and name not in known), key=lambda row: (-row[1], row[0]))


def outside_note(languages: list[tuple[str, int]] | None) -> str:
    named = ", ".join(f"{name} ({count:,} file{'' if count == 1 else 's'})" for name, count in (languages or [])[:6])
    return f"Not written for {named}, so few or none there doesn't mean few or none exist." if named else ""


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


def left_out_hits(root: Path, names: list[str]) -> tuple[list[Hit], bool]:
    """Lines naming any of these, as whole words, in files a search leaves out: a folder called build at any depth is one, and it can hold real callers. The bool says it stopped short."""
    if not names:
        return [], False
    kept = set(selected_files(root, None))
    if filesystem.in_git(root):
        source = _git_hits(root, names, None, True, True, False)
    else:
        files = []
        for folder, subfolders, entries in os.walk(root):
            subfolders[:] = [name for name in subfolders if name not in _NEVER_CALLERS]
            prefix = os.path.relpath(folder, root).replace(os.sep, "/")
            files += [path for path in (entry if prefix == "." else f"{prefix}/{entry}" for entry in entries) if path not in kept and language_at(root, path)]
            if len(files) >= MAX_LEFT_OUT_FILES:
                break
        source = _walk_hits(root, files[:MAX_LEFT_OUT_FILES], names, True, True, False)
    hits = []
    for hit in source:
        if hit.path not in kept:
            hits.append(hit)
            if len(hits) >= MAX_LEFT_OUT_HITS:
                source.close()
                return sorted(hits), True
    return sorted(hits), False


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
