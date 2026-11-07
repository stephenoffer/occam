"""Does documentation match the code it describes, and how does its prose read?

Facts are checked here, because a rewrite for voice is when they slip and the rewriter is otherwise checking itself.
Prose belongs to human-voice, a separate and optional install, so its linter runs as its own program and its absence is
reported rather than hidden. Nothing a document shows is ever run.
"""

from __future__ import annotations

import ast
import bisect
import builtins
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import warnings
from collections import Counter
from itertools import dropwhile
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, NamedTuple
from urllib.parse import unquote

from . import files as filesystem
from .manifests import stdlib_modules
from .source import EXTENSIONS, language_of

MARKDOWN = {".md", ".markdown", ".mdx"}
OTHER_PROSE = {".rst", ".adoc", ".org", ".txt"}
_CONFIG_SUFFIXES = {".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".env", ".example", ".properties"}
_CONFIG_NAMES = re.compile(r"(^|/)(Makefile|Dockerfile|Justfile|requirements[^/]*\.txt)$")
# One-letter suffixes are left out because `obj.r` and `args.c` are far more often attributes than files.
_PATH_SUFFIXES = {suffix for suffix in {*EXTENSIONS, *MARKDOWN, *OTHER_PROSE, *_CONFIG_SUFFIXES} if len(suffix) > 2}
_WEB_NAMES = {"com", "org", "net", "io", "dev", "ai", "edu", "gov", "co"}
_MAX_FILES = 20_000
_LEADS_SHOWN = 12
_LONGEST_NAME = 300  # anything longer isn't a name or a path someone typed
_LINT_SECONDS = 60

_FENCE = re.compile(r"^\s*(`{3,}(?!`)(?!.*`)|~{3,})\s*([\w+-]*)")  # CommonMark bars a backtick from a backtick fence's info string, so ```foo``` is inline code and opens nothing
_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
_BACKTICKS = re.compile(r"`+")
_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)")
_REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*<?([^\s>]+)", re.M)
_HTML_LINK = re.compile(r"""\b(?:href|src|srcset)=["']([^"'\s]+)""")
_URL = re.compile(r"\bhttps?://[^\s<>()\[\]\"'`]+")
_HAS_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
_EXTERNAL_TARGET = re.compile(r"\]\(\s*<?[a-z][a-z0-9+.-]*:", re.I)

_WORD = re.compile(r"[A-Za-z_]\w*")
_FLAG_WORD = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")
_FLAG = re.compile(r"^(--[A-Za-z][\w-]*)(?:=\S*)?$")
_CALL = re.compile(r"^([A-Za-z_][\w.:]*)\(.*\)$")
_DOTTED = re.compile(r"^[A-Za-z_]\w*(?:(?:\.|::)[A-Za-z_]\w*)+$")
_SNAKE = re.compile(r"^_*[A-Za-z][A-Za-z0-9]*(?:_+[A-Za-z0-9]+)+_*$")
_CAMEL = re.compile(r"^(?:[a-z]+|[A-Z][a-z0-9]+)[A-Z]\w*$")
_NOT_A_PATH = re.compile(r"\s|[*?<>{}$\[\]|=@,;()'\"`\\]|\.\.\.|^[~/-]|://")
_LOCATION = re.compile(r"(?::\d+(?:[-:]\d+)*|#L\d+(?:-L?\d+)?)$")  # file.py:12, file.py:12:5, file.py:36-38, file.py#L3-L9

_PYTHON_FENCES = {"python", "python3", "py", "pycon"}
_SHELL_FENCES = {"bash", "sh", "shell", "zsh", "console", "shell-session", "terminal"}
_INTERPRETER = re.compile(r"python[\d.]*|node|deno|bun|bash|sh|zsh|ruby|perl")
_SHELL_OPERATOR = re.compile(r"\s(?:&&|\|\||\||;)\s")
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
_NOT_OURS = re.compile(r"[~/$<]|\.?venv/|node_modules/")

_LIST_MARKER = re.compile(r"^[ \t]*\d+[.)][ \t]", re.M)
_NUMBER = re.compile(r"(?<![\w.])[$€£]?v?\d(?:[\d,.:/-]*\d)?(?:%|[A-Za-z]{1,3}\b)?")

_LINTER = ("human-voice", "scripts", "detect_ai_prose.py")
_USER_SKILLS = (".claude/skills", ".agents/skills", ".gemini/skills", ".cursor/skills", ".copilot/skills", ".codeium/windsurf/skills", ".cline/skills", ".config/opencode/skills")
_PROJECT_SKILLS = (".claude/skills", ".agents/skills", ".gemini/skills", ".cursor/skills", ".github/skills", ".windsurf/skills", ".cline/skills", ".opencode/skills")
_LIMITS = ("What this can't see: whether what a document says about a name is true, signatures, defaults, behavior and heading anchors. "
           "It reads examples and runs none of them, so run them yourself. Leads can also be third-party names, so triage them.")


class Fence(NamedTuple):
    language: str
    line: int
    body: str


class Index(NamedTuple):
    names: set[str]
    flags: set[str]
    paths: set[str]
    commands: set[str]
    stdlib: set[str]
    partial: bool


class Lead(NamedTuple):
    line: int
    rule: str
    message: str


def is_markdown(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in MARKDOWN


def _exists(path: Path) -> bool:
    """A document can name anything, including a path too long for the system to look up."""
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------- reading a document

def _split_fences(text: str) -> tuple[list[Fence], str]:
    """Code blocks, and the rest with each block blanked so line numbers still hold. An unclosed block runs to the end, as it renders."""
    fences: list[Fence] = []
    prose: list[str] = []
    opener, language, start = "", "", 0
    body: list[str] = []
    for number, line in enumerate(text.split("\n"), 1):
        if opener:
            closing = line.strip()
            if closing and set(closing) == {opener[0]} and len(closing) >= len(opener):
                fences.append(Fence(language, start, "\n".join(body)))
                opener = ""
            else:
                body.append(line)
            prose.append("")
            continue
        found = _FENCE.match(line)
        if found:
            opener, language, start, body = found.group(1), found.group(2).lower(), number + 1, []
            prose.append("")
        else:
            prose.append(line)
    if opener:
        fences.append(Fence(language, start, "\n".join(body)))
    return fences, "\n".join(prose)


def blank_fences(text: str) -> tuple[str, bool]:
    """The text with code blocks blanked, keeping line numbers, and whether one was left open: a line added after the end only disappears inside a block."""
    return _split_fences(text)[1], _split_fences(text + "\nx")[1].endswith("\n")


def _blank(match: re.Match) -> str:
    return "\n" * match.group(0).count("\n")


def _line_finder(text: str) -> Callable[[int], int]:
    """Offset to line number. Counting newlines per match would be quadratic on a document built to be slow."""
    starts = [match.end() for match in re.finditer("\n", text)]
    return lambda offset: bisect.bisect_right(starts, offset) + 1


def _span_extents(prose: str) -> Iterator[tuple[int, int, int]]:
    """Each inline code span as start, end, and the length of its backtick run. A run closes at the next run of the same length on its line.

    One pass over the runs, because a regex rescans the line for every opener that never closes.
    """
    offset = 0
    for line in prose.split("\n"):
        runs = [(match.start(), match.end()) for match in _BACKTICKS.finditer(line)]
        closes_at: list[int | None] = [None] * len(runs)
        latest: dict[int, int] = {}
        for position in range(len(runs) - 1, -1, -1):
            length = runs[position][1] - runs[position][0]
            closes_at[position] = latest.get(length)
            latest[length] = position
        position = 0
        while position < len(runs):
            closing = closes_at[position]
            if closing is None:
                position += 1
                continue
            yield offset + runs[position][0], offset + runs[closing][1], runs[position][1] - runs[position][0]
            position = closing + 1
        offset += len(line) + 1


def _spans(prose: str, in_external_links: bool = True) -> dict[str, int]:
    """Each inline code span with the line it first appears on. A path in the text of a link to another site belongs to that site, so a check against this repository leaves it out."""
    line_of = _line_finder(prose)
    found: dict[str, int] = {}
    for start, end, ticks in _span_extents(prose):
        if in_external_links or not _EXTERNAL_TARGET.match(prose, end):
            found.setdefault(prose[start + ticks:end - ticks].strip(), line_of(start))
    return found


def _without_spans(prose: str) -> str:
    pieces, position = [], 0
    for start, end, _ in _span_extents(prose):
        pieces.append(prose[position:start])
        position = end
    pieces.append(prose[position:])
    return "".join(pieces)


def _links(prose_without_spans: str) -> dict[str, int]:
    line_of = _line_finder(prose_without_spans)
    found: dict[str, int] = {}
    for pattern in (_LINK, _REFERENCE_LINK, _HTML_LINK):
        for match in pattern.finditer(prose_without_spans):
            found.setdefault(match.group(1), line_of(match.start(1)))
    return found


# ---------------------------------------------------------------- what the repository actually has

def _entry_points(root: Path) -> set[str]:
    """Commands this project installs, so that `mytool --flag` in a document can be checked as this project's own."""
    names: set[str] = set()
    pyproject = filesystem.read_text(root / "pyproject.toml") or ""
    for section in re.findall(r"^\[(?:project\.(?:gui-)?scripts|tool\.poetry\.scripts)\]\n(.*?)(?=^\[|\Z)", pyproject, re.M | re.S):
        names.update(re.findall(r'^"?([\w.-]+)"?\s*=', section, re.M))
    try:
        package = json.loads(filesystem.read_text(root / "package.json") or "{}")
    except (ValueError, RecursionError):
        return names
    programs = package.get("bin") if isinstance(package, dict) else None
    if isinstance(programs, dict):
        names.update(programs)
    elif isinstance(programs, str) and isinstance(package.get("name"), str):
        names.add(package["name"].split("/")[-1])
    return names


def build_index(root: Path) -> Index:
    """Every word in the code, so a document naming something invented stands out. A name found here may still be the wrong one: this is a floor."""
    names, flags, paths = {*dir(builtins), "NaN"}, set(), set()  # NaN is shaped like camelCase and belongs to no project
    listed = filesystem.list_files(root, None, filesystem.load_config(root))
    for relative in listed[:_MAX_FILES]:
        parts = relative.split("/")
        paths.update("/".join(parts[start:]) for start in range(len(parts)))  # documents often shorten a path to its tail
        suffix = PurePosixPath(relative).suffix.lower()
        named = bool(_CONFIG_NAMES.search(relative))
        if suffix and not named and not language_of(relative) and suffix not in _CONFIG_SUFFIXES:
            continue
        text = filesystem.read_text(root / relative)
        if text is None or (not suffix and not named and not text.startswith("#!")):
            continue
        names.update(_WORD.findall(text))
        flags.update(_FLAG_WORD.findall(text))
    return Index(names, flags, paths, _entry_points(root), stdlib_modules(), len(listed) > _MAX_FILES)


# ---------------------------------------------------------------- comparing a document with the repository

def _module_exists(root: Path, module: str) -> bool:
    path = module.replace(".", "/")
    return any(_exists(root / folder / name) for folder in ("", "src") for name in (path, f"{path}.py"))


def _path_exists(path: str, folder: Path, root: Path, index: Index) -> bool:
    return path.rstrip("/") in index.paths or _exists(root / path) or _exists(folder / path)


def _looks_like_path(span: str, root: Path) -> bool:
    """A known suffix, an explicit relative start, or a folder this repository has. `and/or` and `application/json` have none of those."""
    if _NOT_A_PATH.search(span):
        return False
    pure = PurePosixPath(span)
    if pure.suffix.lower() in _PATH_SUFFIXES or span.startswith(("./", "../")):
        return True
    return "/" in span and _exists(root / pure.parts[0])


def _name_lead(line: int, span: str, index: Index) -> Lead | None:
    flag = _FLAG.match(span)
    if flag:
        return None if flag.group(1) in index.flags else Lead(line, "unknown-name", f"flag `{span}` appears nowhere in the code")
    call = _CALL.match(span)
    name = call.group(1) if call else span
    if not call and not (_DOTTED.match(name) or _SNAKE.match(name) or _CAMEL.match(name)):
        return None  # a bare word can't be told from English or a command name
    pieces = re.split(r"\.|::", name)
    if len(pieces) > 1 and (pieces[0] in index.stdlib or pieces[-1] in _WEB_NAMES):
        return None
    return None if pieces[-1] in index.names else Lead(line, "unknown-name", f"`{span}` appears nowhere in the code")


def _span_lead(line: int, span: str, folder: Path, root: Path, index: Index) -> Lead | None:
    if len(span) > _LONGEST_NAME:
        return None
    path = _LOCATION.sub("", span)
    if _looks_like_path(path, root):
        return None if _path_exists(path, folder, root, index) else Lead(line, "missing-path", f"`{span}` doesn't exist here")
    return _name_lead(line, span, index)


def _link_lead(line: int, target: str, folder: Path, root: Path) -> Lead | None:
    """Relative to the document, as it renders. A link that only works from the repository root is broken on the page."""
    if _HAS_SCHEME.match(target) or target.startswith(("#", "//", "{", "<", "$")):
        return None
    path = unquote(re.split(r"[#?]", target, maxsplit=1)[0])
    if not path:
        return None
    resolved = root / path.lstrip("/") if path.startswith("/") else folder / path
    return None if _exists(resolved) else Lead(line, "dead-link", f"link to `{target}` doesn't resolve from this document")


def _parse_python(fence: Fence) -> ast.Module | Lead:
    source = textwrap.dedent(fence.body)
    if re.search(r"^[ \t]*>>>", source, re.M):
        source = "\n".join(re.findall(r"^[ \t]*(?:>>>|\.\.\.) ?(.*)$", source, re.M))  # a doctest: what isn't prompted is output
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # a bad escape in an example is no reason to write to stderr
            return ast.parse(source)
    except SyntaxError as error:
        return Lead(fence.line + (error.lineno or 1) - 1, "bad-example", f"this Python doesn't parse: {error.msg}")
    except (ValueError, RecursionError, MemoryError):
        return Lead(fence.line, "bad-example", "this Python doesn't parse")


def _imports_in(tree: ast.Module) -> Iterator[tuple[int, str, tuple[str, ...]]]:
    """Each import as its line, the module, and the names taken from it. Relative imports say nothing about a reader's setup."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, ()
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.lineno, node.module, tuple(alias.name for alias in node.names if alias.name != "*")


def _python_leads(fence: Fence, root: Path, index: Index) -> list[Lead]:
    tree = _parse_python(fence)
    if isinstance(tree, Lead):
        return [tree]
    leads = []
    for lineno, module, imported in _imports_in(tree):
        line = fence.line + lineno - 1
        top = module.split(".")[0]
        if top in index.stdlib:
            continue
        if top not in index.names:
            leads.append(Lead(line, "unknown-name", f"example imports `{top}`, which appears nowhere in this repository's code or manifests"))
        elif _module_exists(root, top):
            leads += [Lead(line, "unknown-name", f"example imports `{name}` from `{module}`, and it appears nowhere in the code") for name in imported if name not in index.names]
    return leads


def _shell_commands(body: str) -> Iterator[tuple[int, list[str]]]:
    """Each command in a block with its line. Where a block shows prompts, only prompted lines are commands, and the rest is output."""
    lines = body.split("\n")
    prompted = any(line.lstrip().startswith("$ ") for line in lines)
    held: list[str] = []
    held_at = 0
    for offset, raw in enumerate(lines):
        line = raw.strip()
        if prompted and not held:
            if not line.startswith("$ "):
                continue
            line = line[2:]
        if line.endswith("\\"):
            held_at = held_at if held else offset
            held.append(line[:-1])
            continue
        at = held_at if held else offset
        joined = " ".join([*held, line])
        held = []
        for command in _SHELL_OPERATOR.split(joined):
            try:
                words = shlex.split(command, comments=True)
            except ValueError:
                continue  # an unbalanced quote: nothing can be said about this line
            words = list(dropwhile(_ASSIGNMENT.match, words))
            if words:
                yield at, words


def _interpreted(args: list[str]) -> tuple[str, str, list[str]]:
    """What `python3 ...` runs: a script, a module, or nothing nameable, along with the arguments it receives."""
    for position, word in enumerate(args):
        if word in ("-c", "-e"):
            break
        if word == "-m":
            return ("module", args[position + 1], args[position + 2:]) if position + 1 < len(args) else ("", "", [])
        if not word.startswith("-"):
            return "script", word, args[position + 1:]
    return "", "", []


def _command_target(words: list[str], index: Index) -> tuple[str, str, list[str]] | None:
    """What a command runs if this project might own it, as kind, name and arguments. None for anyone else's program."""
    program, arguments = words[0], words[1:]
    if _INTERPRETER.fullmatch(program):
        kind, target, passed = _interpreted(arguments)
        return (kind, target, passed) if kind else None
    if "/" in program or PurePosixPath(program).suffix.lower() in _PATH_SUFFIXES:
        return "script", program, arguments
    return ("installed", program, arguments) if program in index.commands else None


def _target_problem(kind: str, target: str, folder: Path, root: Path, index: Index) -> tuple[bool, str]:
    """Whether this project owns the target, and what's wrong with it if so."""
    if kind == "module":
        if not _module_exists(root, target.split(".")[0]):
            return False, ""
        return True, "" if _module_exists(root, target) else f"module `{target}` doesn't exist here"
    if kind == "script":
        if _NOT_OURS.match(target):
            return False, ""
        return True, "" if _path_exists(target, folder, root, index) else f"`{target}` doesn't exist here"
    return True, ""


def _shell_leads(fence: Fence, folder: Path, root: Path, index: Index) -> list[Lead]:
    """Scripts this project owns must exist, and their flags must appear in the code. Another program's flags aren't ours to judge."""
    leads = []
    for offset, words in _shell_commands(fence.body):
        line = fence.line + offset
        running = _command_target(words, index)
        if running is None:
            continue
        kind, target, arguments = running
        owned, problem = _target_problem(kind, target, folder, root, index)
        if problem:
            leads.append(Lead(line, "missing-path", problem))
        elif owned:
            flags = [(word, _FLAG.match(word)) for word in arguments]
            leads += [Lead(line, "unknown-name", f"flag `{word}` of `{target}` appears nowhere in the code") for word, flag in flags if flag and flag.group(1) not in index.flags]
    return leads


def _fence_leads(fence: Fence, folder: Path, root: Path, index: Index) -> list[Lead]:
    if fence.language in _PYTHON_FENCES:
        return _python_leads(fence, root, index)
    if fence.language in _SHELL_FENCES:
        return _shell_leads(fence, folder, root, index)
    if fence.language == "json":
        try:
            json.loads(fence.body)
        except (ValueError, RecursionError) as error:
            return [Lead(fence.line, "bad-example", f"this JSON doesn't parse: {error}")]
    return []


def document_leads(root: Path, relative: str, text: str, index: Index) -> list[Lead]:
    """Where this document and the repository disagree, in reading order and each said once."""
    folder = (root / relative).parent
    fences, prose = _split_fences(text)
    prose = _COMMENT.sub(_blank, prose)
    found = [_span_lead(line, span, folder, root, index) for span, line in _spans(prose, in_external_links=False).items()]
    found += [_link_lead(line, target, folder, root) for target, line in _links(_without_spans(prose)).items()]
    for fence in fences:
        found += _fence_leads(fence, folder, root, index)
    capped = [Lead(lead.line, lead.rule, lead.message[:_LONGEST_NAME]) for lead in found if lead]  # every name in a message came from the document
    unique = {(lead.rule, lead.message): lead for lead in reversed(capped)}
    return sorted(unique.values())


def fact_findings(root: Path, paths: list[str]) -> list[dict]:
    """Changed documents, as findings `gate` can list. It warns rather than blocks, because a third-party name is a fair lead."""
    index = build_index(root)
    findings = []
    for relative in paths:
        text = filesystem.read_text(root / relative)
        if text is not None:
            findings += [{"rule": lead.rule, "path": relative, "line": lead.line, "message": lead.message, "category": "docs"}
                         for lead in document_leads(root, relative, text, index)]
    return findings


# ---------------------------------------------------------------- what a rewrite changed

def _facts(text: str) -> dict[str, set[str]]:
    """Presence, not counts: merging a sentence that said something twice doesn't lose a fact."""
    fences, prose = _split_fences(text)
    prose = _COMMENT.sub(_blank, prose)
    spans = set(_spans(prose))
    plain = _without_spans(prose)
    links = set(_links(plain)) | {url.rstrip(".,;:!?") for url in _URL.findall(plain)}
    plain = _LIST_MARKER.sub("", _URL.sub(" ", _HTML_LINK.sub(" ", _REFERENCE_LINK.sub(" ", _LINK.sub("]( ", plain)))))
    numbers = {number.replace(",", "") for number in _NUMBER.findall(plain)}
    return {"code block": {fence.body.strip() for fence in fences}, "code": spans, "link": links, "number": numbers}


def _shorten(value: str) -> str:
    first = value.split("\n", 1)[0]
    return first[:100] + ("..." if len(first) > 100 or "\n" in value else "")


def changed_facts(before: str, after: str) -> list[str]:
    old, new = _facts(before), _facts(after)
    changes = []
    for kind in old:
        changes += [f"lost {kind}: {_shorten(value)}" for value in sorted(old[kind] - new[kind])]
        changes += [f"added {kind}: {_shorten(value)}" for value in sorted(new[kind] - old[kind])]
    return changes


# ---------------------------------------------------------------- the human-voice linter

def _version_of(path: str) -> tuple[int, ...]:
    """The version folder in a plugin cache: .../human-voice/<version>/skills/human-voice/scripts/detect_ai_prose.py."""
    return tuple(int(number) for number in re.findall(r"\d+", Path(path).parents[3].name))


def _linter_candidates(root: Path) -> list[Path]:
    """A copy the project pins comes first, then the newest plugin install, then a plain copy."""
    candidates = [root / folder / Path(*_LINTER) for folder in _PROJECT_SKILLS]
    try:
        home = Path.home()
    except RuntimeError:  # no HOME and no password entry, as in some containers
        return candidates
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    cached = glob.glob(str(Path(glob.escape(str(config))) / "plugins" / "cache" / "*" / "human-voice" / "*" / "skills" / Path(*_LINTER)))
    return [*candidates, *(Path(path) for path in sorted(cached, key=_version_of, reverse=True)), *(home / folder / Path(*_LINTER) for folder in _USER_SKILLS)]


def _choose_linter(root: Path, allow_exec: bool) -> tuple[Path | None, Path | None]:
    """The linter to use, and otherwise a copy that needs --allow-exec. Both forms of the path count, so a symlink can't carry repository code past that."""
    refused = None
    for candidate in _linter_candidates(root):
        if not filesystem.is_plain_file(candidate):
            continue
        if not allow_exec and any(path.is_relative_to(root) for path in (candidate, candidate.resolve())):
            refused = refused or candidate
            continue
        return candidate, None
    return None, refused


def _lint(linter: Path, text: str, root: Path, register: str | None) -> dict | str:
    """The result, or why there isn't one. Text goes on stdin so both sides of a comparison pick up the same .humanvoicerc, which is JSON and can't run anything."""
    command = [sys.executable, "-I", str(linter), "--json", *(["--register", register] if register else []), "-"]
    try:
        done = subprocess.run(command, cwd=str(root), input=text, capture_output=True, encoding="utf-8", errors="replace", timeout=_LINT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"timed out after {_LINT_SECONDS}s"
    except OSError as error:
        return f"couldn't start ({error})"
    if done.returncode:
        reason = (done.stderr.strip().splitlines() or ["no error message"])[-1]
        return f"exit {done.returncode}: {reason[:200]}"
    try:
        payload = json.loads(done.stdout)
    except (ValueError, RecursionError):
        return "printed something that isn't JSON"
    return payload if isinstance(payload, dict) and "score" in payload else "printed JSON with no score"


def _voice_line(linter: Path, text: str, before: str | None, root: Path, register: str | None) -> tuple[str, bool]:
    """One line on the prose, and whether the linter ran. A score never fails this command: it's a floor, and versions use different scales."""
    result = _lint(linter, text, root, register)
    if isinstance(result, str):
        return f"voice: FAILED to run, {result}", False
    earlier = _lint(linter, before, root, register) if before is not None else None
    score = f"{earlier['score']} before, {result['score']} now" if isinstance(earlier, dict) else str(result["score"])
    band = result.get("verdict") or "no band, because this older linter's scale differs, so only compare scores from one version"
    counts = Counter(hit.get("category") for hit in result.get("hits", []) if isinstance(hit, dict))
    tells = ", ".join(f"{name} {count}" for name, count in counts.most_common(5)) or "no tells matched"
    return f"voice: {score}, {band}. {tells}", True


def _no_linter_line(refused: Path | None) -> str:
    if refused:
        return f"voice: not run. The human-voice copy at {refused} is inside this repository, so running it runs repository code. Read it, then use --allow-exec."
    return "voice: not run, because human-voice isn't installed anywhere this looks. Don't report the prose as checked."


# ---------------------------------------------------------------- the command

def _documents(root: Path, paths: list[str] | None) -> list[str] | None:
    """Named documents and those in named folders, otherwise what changed and still exists. None without git and without names."""
    if paths:
        listed = filesystem.list_files(root, paths, filesystem.load_config(root))
    else:
        changed = filesystem.changed_lines(root)
        if changed is None:
            return None
        listed = [path for path in changed if _exists(root / path)]
    return sorted(path for path in listed if PurePosixPath(path).suffix.lower() in MARKDOWN | OTHER_PROSE)


def _capped(items: list[str]) -> list[str]:
    extra = [f"    ... and {len(items) - _LEADS_SHOWN} more."] if len(items) > _LEADS_SHOWN else []
    return [f"    {item}" for item in items[:_LEADS_SHOWN]] + extra


class _Run(NamedTuple):
    root: Path
    index: Index
    linter: Path | None
    refused: Path | None
    before: str | None
    old: str | None
    register: str | None


def _fact_section(run: _Run, relative: str, text: str) -> tuple[list[str], bool]:
    if not is_markdown(relative):
        return [NOT_CHECKED_FACTS], False
    leads = document_leads(run.root, relative, text, run.index)
    heading = f"  facts: {len(leads)} {'lead' if len(leads) == 1 else 'leads'}"
    return [heading, *_capped([f"{relative}:{lead.line} {lead.rule}: {lead.message}" for lead in leads])], bool(leads)


def _before_section(run: _Run, text: str) -> tuple[list[str], bool]:
    if run.old is None:
        return [], False
    changes = changed_facts(run.old, text)
    if not changes:
        return [f"  against {run.before}: no number, code, link or code block changed"], False
    return [f"  against {run.before}: {len(changes)} facts changed", *_capped(changes)], True


NOT_CHECKED_FACTS = "  facts: NOT CHECKED, because only Markdown is parsed."


def _document_section(run: _Run, relative: str) -> tuple[list[str], bool, bool]:
    """The report on one document, whether it failed, and whether the linter ran on it."""
    text = filesystem.read_text(run.root / relative)
    if text is None:
        return ["", relative, "  NOT CHECKED: this couldn't be read, or is too large."], True, False
    facts, facts_failed = _fact_section(run, relative, text)
    changes, changes_failed = _before_section(run, text)
    if not run.linter:
        return ["", relative, *facts, *changes, f"  {_no_linter_line(run.refused)}"], facts_failed or changes_failed, False
    voice, linted = _voice_line(run.linter, text, run.old, run.root, run.register)
    return ["", relative, *facts, *changes, f"  {voice}"], facts_failed or changes_failed or not linted, linted


def _refusal(paths: list[str] | None, before: str | None) -> str | None:
    """Why this request can't be checked at all. Saying so beats reporting a clean result on nothing."""
    missing = [path for path in [*(paths or []), *([before] if before else [])] if not _exists(Path(path))]
    if missing:
        return f"No such path: {', '.join(missing)}. Nothing was checked."
    if before and (len(paths or []) != 1 or Path(paths[0]).is_dir()):
        return "--before compares one document with its earlier copy, so name exactly one document. Nothing was checked."
    if before and filesystem.read_text(Path(before)) is None:
        return f"Couldn't read {before}. Nothing was checked."
    return None


def check(root: Path, paths: list[str] | None = None, before: str | None = None, register: str | None = None, allow_exec: bool = False) -> tuple[str, int]:
    """Every document's facts and voice. Exit 1 when a fact is in doubt, the linter broke or a document couldn't be read. Exit 2 when no document had its facts checked, even if the linter ran, since a voice score says nothing about them."""
    refusal = _refusal(paths, before)
    if refusal:
        return refusal, 2
    documents = _documents(root, paths)
    if documents is None:
        return ("Not a git repository, so there's no diff to read. Name the documents: `occam docs README.md docs/`.", 2)
    if not documents:
        return (f"No documents in {', '.join(paths)}. Nothing was checked.", 2) if paths else ("No changed documents.", 0)
    linter, refused = _choose_linter(root, allow_exec)
    run = _Run(root, build_index(root), linter, refused, before, filesystem.read_text(Path(before)) if before else None, register)
    lines = [f"occam docs: {len(documents)} documents." if len(documents) > 1 else "occam docs: 1 document."]
    failed, linted, facts_checked = False, False, False
    for relative in documents:
        section, section_failed, section_linted = _document_section(run, relative)
        lines += section
        failed = failed or section_failed
        linted = linted or section_linted
        facts_checked = facts_checked or (NOT_CHECKED_FACTS not in section and not any(line.startswith("  NOT CHECKED") for line in section)) or (run.old is not None and NOT_CHECKED_FACTS in section)
    lines.append("")
    if run.index.partial:
        lines.append(f"Only the first {_MAX_FILES} files were read for names, so a real name can look unknown here.")
    if linted:
        lines.append(f"Voice came from {linter}. It's a floor that doesn't show the prose reads well, so don't write to the number.")
    lines.append(_LIMITS)
    if not facts_checked and not failed:
        lines.append("No document had its facts checked, so this is no clean result.")
        return "\n".join(lines), 2
    return "\n".join(lines), 1 if failed else 0
