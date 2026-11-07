"""Python facts stated before the work, while they can still change it. Nothing here holds anything."""

from __future__ import annotations  # the stock macOS python3 is 3.9

import ast
import re
import sys
import textwrap
import warnings
from pathlib import Path
from typing import Callable

# sys.stdlib_module_names is from 3.10, and the stock macOS python3 is 3.9. These are the names people reach for.
COMMON_STDLIB_NAMES = {"abc", "ast", "base64", "calendar", "cmd", "code", "collections", "copy", "csv", "dataclasses", "datetime",
                       "decimal", "email", "enum", "functools", "glob", "hashlib", "html", "http", "inspect", "io", "json", "logging",
                       "math", "operator", "parser", "pathlib", "platform", "profile", "queue", "random", "re", "secrets", "select",
                       "shutil", "signal", "site", "socket", "ssl", "statistics", "string", "struct", "sys", "tempfile", "test", "time",
                       "token", "tokenize", "trace", "types", "typing", "uuid", "warnings", "xml"}
STDLIB_NAMES = getattr(sys, "stdlib_module_names", COMMON_STDLIB_NAMES)


def shadow_note(relative: str, already_exists: bool) -> str | None:
    """A new module named after a standard library one, which breaks scripts run from its folder."""
    path = Path(relative)
    if already_exists or path.suffix != ".py" or path.stem.startswith("__") or path.stem not in STDLIB_NAMES:
        return None
    return (f"{relative} would share its name with the standard library's `{path.stem}`. Inside a package that only bites when "
            "a script in the same folder runs directly, because Python puts that folder first on the import path, and the "
            "standard library's own imports then find this file. A different name avoids the question.")


# What the Python references say that agents most need, stated when the trap is in the code being written, because
# measured runs showed they almost never open a reference. Each is (key, pattern, an argument that makes the call safe,
# a pattern the edit or its file must also contain, fact). Patterns stay bounded, because this runs on every Python edit.
PANDAS_NEARBY = r"\b(?:pandas|pd|df\w{0,20}|[a-z]\w{0,20}_df)\b"
TRAPS = (
    ("subprocess", r"\bsubprocess\.run\(", "check=", None, "`subprocess.run` doesn't raise on a non-zero exit without `check=True`, so a failed command looks like success. It has no default timeout either."),
    ("requests-timeout", r"\brequests\.(?:get|post|put|patch|delete|head|request)\(", "timeout=", None, "`requests` has no default timeout, so this call can hang forever."),
    ("taskgroup", r"\bTaskGroup\b", None, None, "`asyncio.TaskGroup` raises an `ExceptionGroup`, so `except ValueError` around it misses a task's `ValueError`. Use `except*`, or handle it inside the task."),
    ("to-thread", r"\bto_thread\(", None, None, "Cancelling `asyncio.to_thread` cancels the wait, not the thread, which runs to completion."),
    ("submit", r"(?i:\b\w{0,40}(?:executor|pool))\.submit\(", None, None, "`executor.submit` keeps an exception in the future until something calls `.result()` or `.exception()`."),
    ("create-task", r"^[ \t]*asyncio\.create_task\(", None, None, "The event loop keeps only a weak reference to a task, so one nobody holds can vanish mid-run. Keep a reference."),
    ("cancelled", r"\bexcept[ \t]+(?:asyncio\.)?CancelledError\b", None, None, "`CancelledError` has to propagate unless this code cancelled that task itself, so re-raise it after any cleanup."),
    ("utcnow", r"\b(?:datetime|dt)\.(?:utcnow|utcfromtimestamp)\(", None, None, "`datetime.utcnow()` is deprecated from 3.12 and returns a naive value. Use `datetime.now(timezone.utc)`."),
    ("get-event-loop", r"\basyncio\.get_event_loop\(|(?<![\w.])get_event_loop\(", None, None, "`asyncio.get_event_loop()` raises `RuntimeError` on 3.14 when no loop is running. Use `asyncio.run()` or `get_running_loop()`."),
    ("pkg-resources", r"\bpkg_resources\b", None, None, "`pkg_resources` is deprecated and gone from current setuptools. Use `importlib.metadata` or `importlib.resources`."),
    ("pydantic-v1", r"@(?:root_)?validator\(|\.parse_obj\(|\borm_mode\b|\bfrom pydantic import (?:\([^)]{0,300}|[^\n(]{0,200})\bBaseSettings\b", None, None, "In Pydantic this is the v1 API. v2 uses `@field_validator`, `@model_validator`, `.model_validate()`, `from_attributes`, and `BaseSettings` from `pydantic-settings`. Check the installed version."),
    ("openai-v0", r"\bopenai\.(?:Chat)?Completion\.", None, None, "This is the pre-1.0 OpenAI client. Current versions use `OpenAI().chat.completions.create()`. Check the installed version."),
    ("numpy-alias", r"\bnp\.(?:float|int|NaN)\b", None, None, "`np.float` and `np.int` were removed in NumPy 1.24, and `np.NaN` in 2.0."),
    ("mock-patch", r"(?<![\w.])patch\(\s*f?[\"']|\b(?:mock|mocker)\.patch\(", None, None, "Patch where the name is looked up, not where it's defined: after `from os.path import exists` in `lib.py`, that's `lib.exists`. A plain `Mock` accepts any call, so use `autospec=True`."),
    ("raises-exception", r"\bpytest\.raises\(\s*(?:Base)?Exception\b", None, None, "`pytest.raises(Exception)` also accepts the wrong error. Name the type and use `match=`."),
    ("tarfile", r"\.extractall\(", "filter=", r"\btarfile\b", "`tarfile.extractall` before 3.14 allows traversal and link attacks by default. Pass `filter=\"data\"` where available, and don't extract untrusted archives without inspecting them."),
    ("template-injection", r"(?:\bjinja2\.|(?<![\w.]))Template\((?!\s*f?[\"'])|\.from_string\((?!\s*f?[\"'])", None, r"\b(?:jinja2|Environment)\b", "A Jinja2 template built from outside input runs code, even with autoescaping. Use a fixed template with the input as data."),
    ("cache-method", r"@(?:functools\.)?(?:lru_)?cache\b[^\n]{0,200}\n[ \t]*def \w{1,100}\(self\b", None, None, "A cache on a method keeps instances alive until they are evicted, and for good with an unbounded cache."),
    ("type-checking", r"^[ \t]*if (?:typing\.)?TYPE_CHECKING:", None, None, "Names imported here don't exist at runtime, so Pydantic and `typing.get_type_hints` fail on annotations using them."),
    ("chained-assign", r"\b(?:[a-z]\w{0,20}_)?df\w{0,20}\[[^\n]{1,200}\]\[[^\]\n]{1,100}\][ \t]*=[^=]", None, None, "`df[mask][\"b\"] = x` changes nothing under Copy-on-Write, the default in current pandas. Use `df.loc[mask, \"b\"] = x`."),
    ("merge-grain", r"\.merge\(", "validate=", PANDAS_NEARBY, "`merge` on duplicate keys multiplies rows without complaint. `validate=\"one_to_one\"` or `\"many_to_one\"` states the grain and raises otherwise."),
    ("groupby-nan", r"(?<!itertools)\.groupby\(", "dropna=", PANDAS_NEARBY, "`groupby` drops NaN keys by default, which silently loses rows from totals. `dropna=False` keeps them."),
)
_COMPILED_TRAPS = tuple((key, re.compile(pattern, re.M), unless, re.compile(also) if also else None, fact) for key, pattern, unless, also, fact in TRAPS)
TUPLE_ASSERT_FACT = "`assert (x, \"message\")` is a non-empty tuple, so it can never fail. Drop the parentheses."
MAX_FACTS_PER_EDIT = 3
SKILL = "occam-python"
MAX_SCANNED_CHARS = 50_000
MAX_CALL_CHARS = 2_000
MAX_CALLS_CHECKED = 50
COMMENT_LINE = re.compile(r"^[ \t]*#[^\n]*", re.M)

NOTEBOOK_FACT = ("A notebook is verified only when a fresh kernel runs it top to bottom. A cell can use a name only a later cell "
                 "defines, and saved outputs show what happened once, not what the code does now. Stale outputs mislead. If no kernel can run here, "
                 "say so, and either execute the code cells in order in a new process and save what they print, saying it wasn't Jupyter, or clear them "
                 "and say a rerun will fill them. More is at {path}.")
TEST_FACT = ("Python suites stay green while checking nothing when two tests share a name (the first never runs), a `Test*` class "
             "has `__init__` (never collected), or `-k` matches nothing behind a pipe. `--collect-only -q` shows what really runs. "
             "More is at {path}.")
AUDIT_FACT = ("Auditing Python: a clean lint isn't the audit. Read the tests as suspects, because a test asserting only on a mock "
              "can stay green when behavior breaks, so report those too. `ignore_missing_imports` hides packages that don't exist, "
              "and `import` or `--collect-only` run code. More is at {path}.")
SPLIT_FACT = ("Splitting a Python module: do all of the split that was asked for, and say what stayed and why. Old import paths, "
              "`mock.patch` strings, task names and pickles break at runtime rather than at import. Import each new module alone "
              "in a fresh process. More is at {path}.")
SPLIT_REQUEST = re.compile(r"\bsplit(?:ting)?\b[^\n]{0,40}\b(?:modules?|packages?|files)\b|\bsplit(?:ting)?\s+(?:up\s+)?\S{1,80}\.py\b"
                           r"|\bsplit(?:ting)?\s+(?:up\s+)?(?:this|the)\s+(?:file|class)\b(?!\s+(?:paths?|names?|contents?|by|on)\b)"
                           r"|\b(?:break|split|pull|carve)(?:ing)?\s+(?:\w{1,20}\s+){0,3}(?:up|apart)\b[^\n]{0,60}(?:\b(?:modules?|packages?|files?|class)\b|\.py\b)"
                           r"|\b(?:module|package)\b[^.\n]{0,40}\b(?:split|broken up)\b|\b(?:this|the) file\b[^.\n]{0,40}\bsplit\b", re.I)
AUDIT_REQUEST = re.compile(r"\baudit(?:ing)?\s+(?:this|the|our|my|these|those|all|\S{1,80}\.py\b)|\baudit of\b"
                           r"|\b(?:go|look|read)(?:ing)?\s+through\b[^\n]{0,80}\b(?:wrong|problems?|issues?|bugs?|defects?)\b", re.I)
NOTEBOOK_REQUEST = re.compile(r"\.ipynb\b|\b(?:this|the|my|our)\s+notebook\b|\bnotebook\s+cells?\b", re.I)
# Agents often write code through the shell, so the same facts apply to a redirect, or an inline script that writes.
SHELL_WRITES_PYTHON = re.compile(r"(?:>>?|\btee\s(?:\s*-a)?)\s*[\"']?([\w./-]{1,200}\.pyi?)\b")
INLINE_WRITE = re.compile(r"\.write_text\(|\bopen\([^)\n]{0,200}[\"'][wax]b?\+?[\"']")


def _arguments(text: str, start: int) -> str:
    """A call's arguments, from just after its opening parenthesis, balancing brackets. Strings aren't parsed."""
    depth = 1
    for index in range(start, min(len(text), start + MAX_CALL_CHARS)):
        if text[index] in "([{":
            depth += 1
        elif text[index] in ")]}":
            depth -= 1
            if not depth:
                return text[start:index]
    return text[start:start + MAX_CALL_CHARS]


def _has_tuple_assert(text: str) -> bool:
    if "assert" not in text:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(textwrap.dedent(text))
    except (SyntaxError, ValueError, RecursionError, MemoryError):  # an edit is often a fragment, which is fine to skip
        return False
    return any(isinstance(node, ast.Assert) and isinstance(node.test, ast.Tuple) and node.test.elts for node in ast.walk(tree))


def _fires(pattern: re.Pattern, unless: str | None, text: str) -> bool:
    if unless is None:
        return bool(pattern.search(text))
    for count, match in enumerate(pattern.finditer(text)):
        if count >= MAX_CALLS_CHECKED:
            return False
        if unless not in _arguments(text, match.end()):
            return True
    return False


def edit_facts(relative: str, is_test: bool, written: str, reference: Callable[[str, str], str],
               file_text: Callable[[], str] = str) -> list[tuple[str, str]]:
    """The (key, fact) pairs for this edit, most specific first. The caller says each key once per session."""
    facts = []
    if relative.endswith(".ipynb"):
        facts.append(("python-notebooks", NOTEBOOK_FACT.format(path=reference("notebooks", SKILL))))
    if is_test:
        facts.append(("python-testing", TEST_FACT.format(path=reference("testing", SKILL))))
    text = COMMENT_LINE.sub("", written[:MAX_SCANNED_CHARS])
    surrounding = None
    for key, pattern, unless, also, fact in _COMPILED_TRAPS:
        if not _fires(pattern, unless, text):
            continue
        if also is not None and not also.search(text):
            surrounding = file_text()[:MAX_SCANNED_CHARS] if surrounding is None else surrounding  # an edit is often only a fragment
            if not also.search(surrounding):
                continue
        facts.append((f"python-{key}", fact))
    if _has_tuple_assert(text):
        facts.append(("python-tuple-assert", TUPLE_ASSERT_FACT))
    return facts


def written_text(tool_input: dict) -> str:
    """The new text in an edit, leaving out what it replaces, since fixing a trap shouldn't be told about that trap."""
    parts = [tool_input.get(key) for key in ("new_string", "content", "new_source")]
    edits = tool_input.get("edits")
    parts += [edit.get("new_string") for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else []
    return "\n".join(part for part in parts if isinstance(part, str))


def read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    except OSError:
        return ""


def say_once(session, mark: Callable[[str], None], facts: list[tuple[str, str]]) -> list[str]:
    """At most MAX_FACTS_PER_EDIT of these that this session hasn't heard. `mark` records one as heard."""
    fresh = [(key, fact) for key, fact in facts if not session.has("mentioned", key)][:MAX_FACTS_PER_EDIT]
    for key, _ in fresh:
        mark(key)
    return [fact for _, fact in fresh]


def edit_notes(relative: str, target: Path, is_test: bool, tool_input: dict, reference: Callable[[str, str], str],
               session, mark: Callable[[str], None]) -> list[str]:
    """Everything to say before this Python edit, leaving out what this session has already heard."""
    shadow = shadow_note(relative, target.exists())
    facts = edit_facts(relative, is_test, written_text(tool_input), reference, lambda: read_source(target))
    return ([shadow] if shadow else []) + say_once(session, mark, facts)


def prompt_facts(words: str, reference: Callable[[str, str], str]) -> list[tuple[str, str]]:
    """The (key, fact) pairs for a request about existing Python, stated before any work starts."""
    facts = []
    if AUDIT_REQUEST.search(words):
        facts.append(("python-audit", AUDIT_FACT.format(path=reference("auditing", SKILL))))
    if SPLIT_REQUEST.search(words):
        facts.append(("python-split", SPLIT_FACT.format(path=reference("structure", SKILL))))
    if NOTEBOOK_REQUEST.search(words):
        facts.append(("python-notebooks", NOTEBOOK_FACT.format(path=reference("notebooks", SKILL))))
    return facts


def shell_notes(command: str, cwd: str, test_path: re.Pattern, reference: Callable[[str, str], str],
                session, mark: Callable[[str], None]) -> list[str]:
    """What to say before a shell command that writes Python or touches a notebook. Ordinary commands add nothing."""
    command = command[:MAX_SCANNED_CHARS]
    targets = SHELL_WRITES_PYTHON.findall(command)
    shadows = [note for note in (shadow_note(target, Path(cwd, target).exists()) for target in targets) if note]
    facts = []
    if ".ipynb" in command:
        facts.append(("python-notebooks", NOTEBOOK_FACT.format(path=reference("notebooks", SKILL))))
    if any(test_path.search(target) for target in targets):
        facts.append(("python-testing", TEST_FACT.format(path=reference("testing", SKILL))))
    if targets or INLINE_WRITE.search(command):
        facts += edit_facts("shell.py", False, command, reference)
    return shadows + say_once(session, mark, facts)
