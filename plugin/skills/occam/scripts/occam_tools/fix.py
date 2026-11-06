"""Mechanical Python repairs that can prove they did only what they say.

Removing a comment must leave an identical AST. That's a real proof, so plain assistant chatter goes by default.

Removing an import must leave exactly the AST you'd get by deleting those names. That proves the edit, not that the import was unneeded: Python can reach a name
through another module, a string, getattr, a doctest or a type comment, and importing can have side effects. So import removal runs only when asked for by name,
only for standard library modules, and only when nothing suggests the name is reached some other way. A project's own linter usually does this better.

Python only: without a parser, a line that looks like a comment may be inside a string, so other languages aren't touched.
A file with uncommitted changes, or claimed by another agent, is left alone, and findings are recomputed from the very bytes being edited.
"""

from __future__ import annotations

import ast
import copy
import difflib
import hashlib
import os
import re
import tempfile
import tokenize
from io import BytesIO, StringIO
from pathlib import Path

from . import files as filesystem, manifests, scan as scanner, workflow
from .py_helpers import DYNAMIC_NAMESPACE

FIXABLE = {"ai-residue", "commented-out-code", "unused-import"}
# Deleting code from comments can lose a derivation or a reason, and removing imports can break things no check here can see, so those need asking for by name.
DEFAULT_RULES = {"ai-residue"}
_KEEPS_A_REASON = re.compile(r"\b(?:because|since|as|so|otherwise|else|license|copyright|author|do not|don'?t|must|never|why|reason|careful|workaround|see|avoid|prevent|until)\b", re.I)
_LONGEST_CHATTER_WORDS = 8
_SIDE_EFFECT_STDLIB = {"this", "antigravity", "readline", "rlcompleter", "site", "logging.config", "encodings", "mimetypes", "faulthandler", "cgitb"}


def _proof(before: str, after: str, removed: dict[int, set[str]]) -> str | None:
    """None if `after` is exactly `before` minus the named imports, with the same docstring. Otherwise why not."""
    try:
        old, new = ast.parse(before), ast.parse(after)
    except SyntaxError as error:
        return f"the result doesn't parse: {error}"
    expected = copy.deepcopy(old)
    body = []
    for node in expected.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno in removed:
            node.names = [alias for alias in node.names if _bound_name(alias) not in removed[node.lineno]]
            if not node.names:
                continue
        body.append(node)
    expected.body = body
    if ast.dump(expected) != ast.dump(new):
        return "the code changed in a way this repair doesn't account for"
    if _declared_encoding(before) != _declared_encoding(after):
        return "a coding comment would move into effect or out of it"
    if ast.get_docstring(old, clean=False) != ast.get_docstring(new, clean=False):
        return "the module's docstring would change"
    return None


def _declared_encoding(text: str) -> str:
    """Only the first two lines can declare an encoding, so removing a line above one changes what the file means."""
    try:
        return tokenize.detect_encoding(BytesIO(text.encode("utf-8", "surrogateescape")).readline)[0]
    except (SyntaxError, UnicodeError):
        return "invalid"


def _bound_name(alias: ast.alias) -> str:
    return alias.asname or alias.name.split(".")[0]


def _comment_lines(text: str) -> set[int]:
    """Lines holding nothing but a comment, according to Python's own tokenizer."""
    lines = set()
    try:
        tokens = list(tokenize.generate_tokens(StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return lines
    for token in tokens:
        if token.type == tokenize.COMMENT and token.line[:token.start[1]].strip() == "":
            lines.add(token.start[0])
    return lines


def _remove_lines(text: str, lines: set[int]) -> str:
    only_comments = _comment_lines(text)
    return "\n".join(content for number, content in enumerate(text.split("\n"), start=1) if number not in lines or number not in only_comments)


def _shift(lines: set[int], gone: set[int]) -> dict[int, int]:
    return {line: line - sum(1 for g in gone if g < line) for line in lines}


def _remove_imports(text: str, names_by_line: dict[int, set[str]]) -> tuple[str, dict[int, set[str]]]:
    """Rewrite the import statements on these lines. Returns the text and what was really removed, skipping anything risky to rewrite."""
    tree = ast.parse(text)
    lines = text.split("\n")
    edits: list[tuple[int, int, str | None]] = []
    done: dict[int, set[str]] = {}
    per_line = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            per_line[node.lineno] = per_line.get(node.lineno, 0) + 1
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)) or node.lineno not in names_by_line:
            continue
        span = lines[node.lineno - 1:node.end_lineno]
        # Several statements on a line, or a comment beside the import, need a person. A comment may explain why it's there.
        if per_line[node.lineno] > 1 or ";" in span[0] or any("#" in line for line in span) or not span[0].lstrip().startswith(("import ", "from ")):
            continue
        unused = names_by_line[node.lineno]
        kept = [alias for alias in node.names if _bound_name(alias) not in unused]
        indent = re.match(r"\s*", span[0]).group()
        if kept:
            rendered = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in kept)
            statement = f"import {rendered}" if isinstance(node, ast.Import) else f"from {'.' * node.level}{node.module or ''} import {rendered}"
            edits.append((node.lineno, node.end_lineno, indent + statement))
        else:
            edits.append((node.lineno, node.end_lineno, None))
        done[node.lineno] = {_bound_name(alias) for alias in node.names} & unused
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1:end] = [replacement] if replacement else []
    return "\n".join(lines), done


def _reachable_from_elsewhere(project, path: str, name: str) -> bool:
    """Could anything reach this name through this module? A file that mentions the module and also uses `.name` or a quoted name might."""
    stem = path.rsplit("/", 1)[-1][:-3]
    mentions_stem = re.compile(rf"\b{re.escape(stem)}\b")
    uses_name = re.compile(rf"\.{re.escape(name)}\b|[\"']{re.escape(name)}[\"']|\bimport\s+.*\b{re.escape(name)}\b|import\s+\*")
    for other in project.files:
        if other != path and other.endswith((".py", ".pyi", ".ipynb", ".cfg", ".toml", ".ini")):
            text = filesystem.read_text(project.root / other) or ""
            if mentions_stem.search(text) and uses_name.search(text):
                return True
    return False


def _named_elsewhere_in_file(text: str, line: int, name: str) -> bool:
    """A doctest, a type comment, globals()["name"]: any other mention, anywhere in this file, might be a use."""
    if DYNAMIC_NAMESPACE.search(text):
        return True  # globals()[computed_name] could reach anything
    lines = text.split("\n")
    return any(re.search(rf"\b{re.escape(name)}\b", content) for number, content in enumerate(lines, start=1) if number != line)


def _statement_at(text: str, line: int) -> ast.AST | None:
    return next((node for node in ast.parse(text).body if node.lineno == line), None)


def _safe_import_removals(project, path: str, findings: list[dict], text: str) -> tuple[dict[int, set[str]], list[str]]:
    """Which unused imports are safe to remove, and notes on those left for a person."""
    if path.rsplit("/", 1)[-1] in ("conftest.py", "__init__.py"):
        return {}, [f"{path}: unused imports here may be fixtures or exports. Check by hand."] if findings else []
    stdlib = manifests.stdlib_modules()
    _, local = project._local_modules()
    modules = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                modules[(node.lineno, _bound_name(alias))] = (getattr(node, "module", None) or alias.name, getattr(node, "level", 0), node)
    safe: dict[int, set[str]] = {}
    notes = []
    for finding in project.refine(findings):
        name = finding["message"].split(" ", 1)[0]
        module, level, statement = modules.get((finding["line"], name), (None, 0, None))
        if module is None:
            continue
        top = module.split(".")[0]
        is_stdlib = not level and top in stdlib and top not in local and module not in _SIDE_EFFECT_STDLIB and "." not in module
        where = f"{path}:{finding['line']}"
        if not is_stdlib:
            notes.append(f"{where}: {name} isn't a plain standard library module, and importing it may have side effects. Check by hand.")
        elif module.startswith("_") or (isinstance(statement, ast.ImportFrom) and project._is_library()):
            notes.append(f"{where}: {name} looks like a re-export, which callers outside this repository may use. Check by hand.")
        elif _named_elsewhere_in_file(text, finding["line"], name):
            notes.append(f"{where}: {name} is mentioned elsewhere in this file, perhaps in a doctest, a type comment or a string. Check by hand.")
        elif _reachable_from_elsewhere(project, path, name):
            notes.append(f"{where}: another file may use {name} through this module. Check by hand.")
        else:
            safe.setdefault(finding["line"], set()).add(name)
    return safe, notes


def _plan(project, path: str, text: str, chosen: set[str], disabled: frozenset = frozenset()) -> tuple[str, dict[int, set[str]], list[str]]:
    """The new text and imports removed, computed from these exact bytes rather than from an earlier scan."""
    findings = [f for f in scanner.scan_text(path, text, "python") if f["rule"] not in disabled]
    notes: list[str] = []
    comment_lines: set[int] = set()
    if "ai-residue" in chosen:
        for finding in findings:
            # Only comments that are plainly an assistant talking, briefly, and that give no reason worth keeping.
            if (finding["rule"] == "ai-residue" and finding["confidence"] == "high" and not _KEEPS_A_REASON.search(finding["evidence"])
                    and len(finding["evidence"].split()) <= _LONGEST_CHATTER_WORDS + 1):
                comment_lines.add(finding["line"])
    if "commented-out-code" in chosen:
        for finding in findings:
            match = re.match(r"(\d+) consecutive", finding["message"]) if finding["rule"] == "commented-out-code" else None
            if match:
                comment_lines.update(range(finding["line"], finding["line"] + int(match.group(1))))
    after = _remove_lines(text, comment_lines)
    removed: dict[int, set[str]] = {}
    if "unused-import" in chosen:
        safe, notes = _safe_import_removals(project, path, [f for f in findings if f["rule"] == "unused-import"], text)
        shifted = _shift(set(safe), comment_lines)
        after, done = _remove_imports(after, {shifted[line]: names for line, names in safe.items()})
        removed = {line: names for line, names in done.items()}
    return after, removed, notes


def _atomic_write(path: Path, data: bytes, expected_digest: str) -> bool:
    """Replace the file only if it still has the content we read, so a concurrent edit isn't lost."""
    if hashlib.sha1(path.read_bytes()).hexdigest() != expected_digest:
        return False
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return True


def _blocked(root: Path, path: str, claims: dict[str, str], dirty: dict[str, str], owner: str | None, allow_dirty: bool, in_git: bool) -> str | None:
    holder = workflow.claim_holder(claims, path)
    if holder and holder != owner:
        return f"claimed by {holder}."
    if allow_dirty:
        return None
    if not in_git:
        return "this isn't a git repository, so nothing shows whose changes are here. --allow-dirty if you're sure."
    if path in dirty:
        return "it has uncommitted changes, which may be someone's work. --allow-dirty only if they're yours."
    if not filesystem.is_plain_file(root / path):
        return "it isn't a regular file."
    return None


def run(root: Path, targets: list[str] | None, rules: list[str] | None, apply: bool, allow_dirty: bool, owner: str | None) -> tuple[str, int]:
    chosen = set(rules or DEFAULT_RULES)
    unknown = chosen - FIXABLE
    if unknown:
        return (f"No codemod for {', '.join(sorted(unknown))}. Those are for you to fix by hand with a check. Codemods exist for: {', '.join(sorted(FIXABLE))}.", 2)
    result = scanner.run_scan(root, targets)
    candidates = sorted({f["path"] for f in result.findings if f["rule"] in chosen})
    in_git = filesystem.in_git(root)
    disabled = frozenset(result.stats.get("config_disabled", []))
    try:
        dirty = filesystem.dirty_paths(root)
    except filesystem.GitProblem as error:
        return f"{error}, so uncommitted work can't be told apart. Nothing was changed.", 2
    claims = workflow.active_claims(root)
    lines: list[str] = []
    skipped_other = sum(1 for path in candidates if not path.endswith(".py"))
    changed = skipped = refused = 0
    for path in (p for p in candidates if p.endswith(".py")):
        reason = _blocked(root, path, claims, dirty, owner, allow_dirty, in_git)
        if reason:
            lines.append(f"skip {path}: {reason}")
            skipped += 1
            continue
        raw = (root / path).read_bytes()
        digest = hashlib.sha1(raw).hexdigest()
        text = raw.decode("utf-8", "surrogateescape")
        if "\r" in text or text.startswith("﻿"):
            lines.append(f"skip {path}: its line endings or byte order mark aren't handled.")
            skipped += 1
            continue
        try:
            after, removed, notes = _plan(result.project, path, text, chosen, disabled)
            problem = _proof(text, after, _original_lines(text, removed)) if after != text else None
        except (SyntaxError, ValueError, RecursionError) as error:
            lines.append(f"skip {path}: {error}")
            skipped += 1
            continue
        lines += notes
        if after == text:
            continue
        if problem:
            lines.append(f"refused {path}: {problem}.")
            refused += 1
            continue
        diff = "".join(difflib.unified_diff(text.splitlines(True), after.splitlines(True), f"a/{path}", f"b/{path}", n=1))
        if apply:
            if not _atomic_write(root / path, after.encode("utf-8", "surrogateescape"), digest):
                lines.append(f"skip {path}: it changed while this ran.")
                skipped += 1
                continue
            lines.append(f"fixed {path}.")
        else:
            lines.append(diff.rstrip("\n"))
        changed += 1
    verb = "Changed" if apply else "Would change"
    lines.append(f"{verb} {changed} files, skipped {skipped}, refused {refused}." + ("" if apply else " Dry run: add --apply to write."))
    if skipped_other:
        lines.append(f"{skipped_other} non-Python files have findings too. Those need fixing by hand, since a comment can't be told from a string here without a parser.")
    if apply and changed:
        lines.append("Each edit was proven to do only what it says, which doesn't prove the import or comment wasn't needed. Run the project's checks. Nothing was committed.")
    return "\n".join(lines), 1 if refused else 0


def _original_lines(text: str, removed: dict[int, set[str]]) -> dict[int, set[str]]:
    """Map imports removed, whose line numbers are after comment removal, back to the original text for the proof."""
    if not removed:
        return {}
    originals = {}
    names = {name for values in removed.values() for name in values}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            hit = {_bound_name(alias) for alias in node.names} & names
            if hit:
                originals[node.lineno] = hit
    return originals

