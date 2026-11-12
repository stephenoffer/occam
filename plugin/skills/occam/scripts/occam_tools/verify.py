"""Evidence instead of claims: did behavior change, can the tests fail, how does it grow, and is this change really done?"""

from __future__ import annotations

import ast
import json
import os
import random
import re
import shlex
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from . import change_checks, design, docs, files as filesystem, manifests, report, reuse, scan as scanner, surgical
from .measure import bench as bench, golden_check as golden_check, golden_record as golden_record  # `occam golden` and `occam bench` reach these through here
from .rules_text import has_secret_assignment, has_secret_shape
from .source import is_test_path, language_of, reads_only_for_secrets
from .workflow import NEEDS_A_SHELL, active_claims, claim_holder, database, needs_a_shell, new_dependencies, scope_problems
from .zero_tests import ran_no_tests

_BLOCKING = {"truncation-marker", "fake-success", "stub-body", "stub-raise", "phantom-import", "phantom-local-import", "phantom-attribute", "undefined-name", "hardcoded-secret",
             "sql-injection", "shell-injection", "tls-disabled", "jwt-unverified", "fail-open", "swallowed-exception", "test-no-assert", "test-tautology", "test-focused", "mutable-default",
             "debug-leftover", "committed-secret-file", "unsafe-deserialize", "dynamic-eval"}
_CONCERNS = [
    ("incomplete", "Implementation is complete"), ("hallucination", "APIs and packages are real"), ("security", "Security"), ("error-masking", "Failures stay visible"),
    ("testing", "Tests can fail"), ("change", "Reached everything it must"), ("pipeline", "Pipelines and infrastructure"), ("scope", "Stayed in scope"), ("complexity", "Complexity"), ("duplication", "No new duplication"), ("overengineering", "No needless structure"),
    ("dead-code", "No dead code left"), ("bloat", "No bloat"), ("comments", "Comments"), ("naming", "Naming"), ("performance", "Performance"),
    ("scalability", "Scalability"), ("architecture", "Architecture"), ("usability", "Usability"), ("reinvention", "Didn't reinvent"), ("language-practice", "Language practice"), ("notebook", "Notebooks"), ("docs", "Documents match the code"),
]
# The paths that need a fresh reviewer: hooks/classify.py SECURITY_CRITICAL and MONEY, which the tools can't import. A test keeps them the same.
_SECURITY_OR_MONEY = re.compile(r"(^|[/_.\-])(auth|authn|authz|oauth|login|sessions?|tokens?|passwords?|secrets?|credentials?|permissions?|acl|rbac|tenants?|tenancy|crypto|signatures?"
                                r"|billing|payments?|invoices?|checkout|refunds?|ledgers?)([/_.\-]|$)", re.I)
_INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "CONTRIBUTING.md", ".cursorrules", ".github/copilot-instructions.md")
_JUDGMENT = [
    "Reread the original request. Is every part of it done, connected and reachable through the real entry point?",
    "Did you honor every constraint the user stated, including ones from earlier in the conversation?",
    "Did you check the layers this touches, and name the ones you didn't? (`occam map` lists them.)",
    "Is the behavior right for empty, huge, malformed and concurrent input, where those can occur?",
    "Did the existing tests that reach this change run on the final state, not only the ones you wrote? `occam query impact --changed` lists them.",
    "Does your report or pull request describe only what the diff contains, and name everything it changed? If you blame a failure on existing code, did you run it on the old code?",
    "Would a maintainer understand this and accept the diff, or call it overcomplicated? Does every changed line trace to the request, to what this change orphaned, or to a fix it had to make?",
]


# ---------------------------------------------------------------- mutation


COPIES: set[str] = set()  # copies `mutate` is using. cli's SIGTERM handler removes them, since it exits without unwinding
_FLIPS = {ast.Eq: "!=", ast.NotEq: "==", ast.Lt: ">=", ast.LtE: ">", ast.Gt: "<=", ast.GtE: "<", ast.Is: "is not", ast.IsNot: "is", ast.In: "not in", ast.NotIn: "in"}
_OP_TEXT = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in"}
_ARITHMETIC = {ast.Add: ("+", "-"), ast.Sub: ("-", "+"), ast.Mult: ("*", "+"), ast.Div: ("/", "*")}
_OUTCOMES = {"failed": "killed", "passed": "survived", "timeout": "timed out", "invalid": "invalid"}  # what a test run says about a breakage. Anything else is an error


def _written(source_lines: list[str], node: ast.AST) -> str:
    """The node's own text. Its columns count UTF-8 bytes."""
    return source_lines[node.lineno - 1].encode()[node.col_offset:node.end_col_offset].decode("utf-8", "replace")


def _mutation_of(node: ast.AST, source_lines: list[str]) -> tuple[int, str, str, str] | None:
    """The breakage for one node, as (search-from column, old text, new text, description), or None."""
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _FLIPS and node.left.end_lineno == node.lineno:
        op = type(node.ops[0])
        return node.left.end_col_offset, _OP_TEXT[op], _FLIPS[op], f"{_OP_TEXT[op]} to {_FLIPS[op]}"
    if isinstance(node, ast.BoolOp) and len(node.values) == 2 and node.values[0].end_lineno == node.lineno:
        word, other = ("and", "or") if isinstance(node.op, ast.And) else ("or", "and")
        return node.values[0].end_col_offset, word, other, f"{word} to {other}"
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC and node.left.end_lineno == node.lineno:
        old, new = _ARITHMETIC[type(node.op)]
        return node.left.end_col_offset, old, new, f"{old} to {new}"
    if isinstance(node, ast.Constant) and node.end_lineno == node.lineno:
        if isinstance(node.value, bool):
            return node.col_offset, str(node.value), str(not node.value), f"{node.value} to {not node.value}"
        if isinstance(node.value, int) and _written(source_lines, node) in ("0", "1"):  # not 0x0 or 0b1, where a new first digit isn't Python
            return node.col_offset, str(node.value), str(node.value + 1), f"{node.value} to {node.value + 1}"
    if isinstance(node, ast.Return) and node.value is not None and node.end_lineno == node.lineno and not (isinstance(node.value, ast.Constant) and node.value.value is None):
        return node.value.col_offset, _written(source_lines, node.value), "None", "return None instead"
    return None


def _mutants(text: str, lines: set[int] | None) -> list[dict]:
    """Small semantic breakages, each one a text replacement on one line."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    source_lines = text.split("\n")
    found: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assert)) or not hasattr(node, "lineno") or (lines is not None and node.lineno not in lines):
            continue
        mutation = _mutation_of(node, source_lines)
        if mutation:
            start, old, new, what = mutation
            current = source_lines[node.lineno - 1]
            position = current.find(old, _char_offset(current, start))
            if position >= 0:
                found.append({"line": node.lineno, "start": position, "old": old, "new": new, "what": what, "source": current})
    return found


def _char_offset(line: str, byte_offset: int) -> int:
    return len(line.encode()[:byte_offset].decode("utf-8", "replace"))


def _copy_project(root: Path, destination: Path) -> None:
    """A link is copied as a link, and nothing is copied through a linked folder, so nothing outside the project is read or written."""
    linked: dict[str, bool] = {}
    real_root = os.path.realpath(root)
    for name in filesystem.tracked_files(root) or filesystem.list_files(root):
        source = root / name
        if filesystem._through_a_link(root, name, linked) or not (source.is_symlink() or source.is_file()):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            # One into the project points at that file's place in the copy, so a test writing through it can't reach the project. One
            # outside it points where it did, as the tests reach it when they run in the project itself.
            pointed = os.path.realpath(source)
            inside = pointed == real_root or pointed.startswith(real_root + os.sep)
            target.symlink_to(os.path.relpath(destination / os.path.relpath(pointed, real_root), target.parent) if inside else pointed)
            continue
        shutil.copy2(source, target, follow_symlinks=False)


def _listing(copy: Path) -> dict[str, tuple]:
    """Everything in the copy, with what shows a file changed. A folder's own times change with what it holds, so only its kind is kept."""
    found = {}
    for folder, folders, names in os.walk(copy):
        for name in folders + names:
            path = os.path.join(folder, name)
            try:
                info = os.lstat(path)
            except OSError:
                continue
            kind = stat.S_IFMT(info.st_mode)
            found[os.path.relpath(path, copy)] = (kind,) if kind == stat.S_IFDIR else (kind, info.st_size, info.st_mtime_ns)
    return found


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        path.unlink()


def _undo_side_effects(root: Path, copy: Path, before: dict[str, tuple], mutated: str) -> list[str]:
    """Puts the copy back as `before` listed it, after a test run: what the run made goes, and what it changed comes back from the project.

    Returns what couldn't come back, because the project's own file has changed since it was copied. The mutated file restores itself.
    """
    after = _listing(copy)
    lost = []
    for name in sorted(set(before) | set(after)):  # a folder sorts before what it holds
        target, was, now = copy / name, before.get(name), after.get(name)
        if now == was or name == os.path.normpath(mutated) or (was is None and not os.path.lexists(target)):
            continue
        try:
            if now is not None and (was is None or now[0] != was[0]):
                _remove(target)
            if was is None:
                continue
            if was[0] == stat.S_IFDIR:
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = root / name
            info = os.lstat(source)
            if (stat.S_IFMT(info.st_mode), info.st_size, info.st_mtime_ns) != was:
                raise OSError("changed since it was copied")
            if os.path.lexists(target):
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
        except OSError:
            lost.append(name)
    return lost


def _run_tests(command: str, cwd: Path, timeout: int) -> tuple[str, str]:
    existing = os.environ.get("PYTHONPATH", "")
    search = os.pathsep.join(filter(None, [str(cwd), str(cwd / "src"), existing]))
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": search}
    try:
        done = filesystem.run_bounded(shlex.split(command), cwd, timeout, env=environment)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except (OSError, ValueError) as error:  # it never ran, so it said nothing about the code
        return "error", str(error)
    return ("passed" if done.returncode == 0 else "failed"), done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")


def _tests_really_use(copy: Path, path: str, command: str, timeout: int) -> bool | None:
    """Make the file impossible to import. If the tests still pass, they aren't testing this copy of it, whether from an editable install or by not importing it.

    None if the run said neither, by timing out or not starting.
    """
    target = copy / path
    original = target.read_bytes()
    target.write_text("raise ImportError('occam: is this the file the tests import?')\n")
    outcome, _ = _run_tests(command, copy, timeout)
    target.write_bytes(original)
    return outcome == "failed" if outcome in ("passed", "failed") else None


def _choose_mutants(root: Path, targets, changed: bool, base, limit: int) -> tuple[list[tuple[str, dict]], int, int]:
    """Candidates from enough files to sample `limit` evenly, and how many files were read of how many there were.

    Files are read in a fixed shuffled order, so a rerun breaks the same things, and stopping early doesn't favour one folder.
    """
    changed_map = filesystem.changed_lines(root, base) if (changed or base) else None
    candidates = filesystem.list_files(root, targets, filesystem.load_config(root))
    if changed_map is not None:
        candidates = [path for path in candidates if path in changed_map]
    sources = sorted(path for path in candidates if language_of(path) == "python" and not is_test_path(path))
    random.Random(0).shuffle(sources)
    mutants: list[tuple[str, dict]] = []
    untracked = set((filesystem.run_git(root, "ls-files", "-o", "--exclude-standard", "-z") or "").split("\0")) if changed_map is not None else set()
    read = 0
    for path in sources:
        if len(mutants) >= limit * 10:
            break
        read += 1
        text = filesystem.read_text(root / path) or ""
        lines = changed_map.get(path) if changed_map is not None else None
        # An untracked file is all new, which an empty set marks. On a tracked file it means the change only deleted lines, so there's nothing to mutate.
        if changed_map is None or lines or path in untracked:
            mutants += [(path, mutant) for mutant in _mutants(text, lines or None)]
    return mutants, read, len(sources)


def _try_mutant(copy: Path, path: str, mutant: dict, command: str, timeout: int) -> str:
    """Runs the tests on the file with this one change. 'invalid' if the change can't be made exactly, or the result isn't Python, and then nothing runs."""
    target = copy / path
    original = target.read_bytes()
    prefix = 0
    while original.startswith(b"\xef\xbb\xbf", prefix):  # the mutant's columns came from filesystem.read_text, which drops these
        prefix += 3
    lines = original[prefix:].split(b"\n")
    number, start, old = mutant["line"] - 1, mutant["start"], mutant["old"]
    try:
        line = lines[number].decode("utf-8")  # strictly, since rewriting a line that isn't UTF-8 would change more than this
    except (IndexError, UnicodeDecodeError):
        return "invalid"
    if line[start:start + len(old)] != old:
        return "invalid"
    lines[number] = (line[:start] + mutant["new"] + line[start + len(old):]).encode("utf-8")
    changed = original[:prefix] + b"\n".join(lines)
    try:
        ast.parse(changed)
    except (SyntaxError, ValueError):
        return "invalid"
    target.write_bytes(changed)
    try:
        outcome, _ = _run_tests(command, copy, timeout)
    finally:
        target.write_bytes(original)
    return outcome


def _shown(source: str) -> str:
    """The line as it was when mutated, unless it looks like it holds a secret, which output that gets pasted mustn't repeat."""
    return "(line withheld: it looks like it holds a secret)" if has_secret_shape(source) or has_secret_assignment(source) else source.strip()[:90]


def _report(results: list[tuple[str, str, dict]], possible: str, timeout: int) -> tuple[list[str], int]:
    """Lines and exit code for what each breakage's run said: only a failing run counts as caught, and anything unexplained leaves the measure incomplete."""
    found: dict[str, list[tuple[str, dict]]] = {}
    for outcome, path, mutant in results:
        found.setdefault(outcome, []).append((path, mutant))
    killed, survived, slow, invalid, errors = (found.pop(kind, []) for kind in ("killed", "survived", "timed out", "invalid", "error"))
    errors += [item for items in found.values() for item in items]
    measured = len(results) - len(invalid)
    out = [f"{len(killed)} of {measured} deliberate breakages were caught ({possible}, sampled evenly). Ran in a temporary copy, and your files weren't touched."]
    if slow:
        out.append(f"{len(slow)} timed out after {timeout}s, so they aren't counted as caught. A breakage that loops forever looks the same as a slow test, and a larger --timeout tells them apart: "
                   + ", ".join(f"{path}:{m['line']} {m['what']}" for path, m in slow[:10]))
    if invalid:
        out.append(f"{len(invalid)} weren't valid Python once changed, so they weren't run or counted.")
    if errors:
        out.append(f"INCOMPLETE: {len(errors)} couldn't be run, or their run gave no answer occam can read, so this isn't a full measure: "
                   + ", ".join(f"{path}:{m['line']} {m['what']}" for path, m in errors[:10]))
    if survived:
        out.append("The tests still pass with these changes, so nothing protects this behavior:")
        out += [f"  {path}:{m['line']}  {m['what']}  ->  {_shown(m['source'])}" for path, m in survived[:25]]
        out.append("Some survivors are equivalent or unimportant. Judge each, and add a test for those that matter.")
    return out, 2 if errors or not measured else 1 if survived or slow else 0


def mutate(root: Path, command: str, targets: list[str] | None, changed: bool, base: str | None, limit: int, timeout: int) -> tuple[str, int]:
    """Break the code on purpose, in a temporary copy, and see whether the tests notice. The working tree isn't touched."""
    if not command.strip():
        return "Give the test command with --cmd.", 2
    if needs_a_shell(command):
        return f"That test command {NEEDS_A_SHELL}", 2
    mutants, read, readable = _choose_mutants(root, targets, changed, base, limit)
    if not mutants:
        return "No mutation points in Python source there. For other languages: Stryker (JS/TS), cargo-mutants (Rust), go-mutesting (Go), PIT (JVM).", 2
    possible = f"{len(mutants)} possible" if read == readable else f"{len(mutants)} possible in the {read} of {readable} files read"
    chosen = mutants[::max(1, len(mutants) // limit)][:limit]
    with tempfile.TemporaryDirectory(prefix="occam-mutate-") as folder:
        COPIES.add(folder)
        try:
            return _mutate_in(root, Path(folder), command, chosen, possible, timeout)
        finally:
            COPIES.discard(folder)


def _mutate_in(root: Path, copy: Path, command: str, chosen: list[tuple[str, dict]], possible: str, timeout: int) -> tuple[str, int]:
    _copy_project(root, copy)
    listing = _listing(copy)  # before any run, so what the tests make, such as .pytest_cache, goes after each breakage
    baseline, output = _run_tests(command, copy, timeout)
    if baseline != "passed":
        return f"The tests don't pass on an unmodified copy ({baseline}), so mutation would mean nothing.\n{output[-800:]}", 2
    if ran_no_tests(output):
        return "That command ran zero tests.", 2
    _undo_side_effects(root, copy, listing, "")  # every run starts from the copy as it was made, so no run's leftovers decide another's
    usable = {}
    for path in sorted({path for path, _ in chosen}):
        usable[path] = _tests_really_use(copy, path, command, timeout)
        _undo_side_effects(root, copy, listing, path)  # what a canary's failing run left behind mustn't reach the next run
    chosen = [item for item in chosen if usable[item[0]] is True]
    notes = []
    unused = [path for path, used in usable.items() if used is False]
    if unused:
        notes.append("Not measured, because the tests still pass when these can't even be imported. Either no test imports them, or the tests import an installed copy: " + ", ".join(unused[:10]))
    unknown = [path for path, used in usable.items() if used is None]
    if unknown:
        notes.append(f"Not measured, because the tests timed out or didn't start when these couldn't be imported, so it isn't known whether they test them: {', '.join(unknown[:10])}")
    again, _ = _run_tests(command, copy, timeout)
    _undo_side_effects(root, copy, listing, "")
    if again != "passed":  # a test that leaves something behind or is flaky would look like it caught every breakage
        return f"The tests passed once on an unmodified copy, then {again} when run again. They leave something behind or they're flaky, so a failure couldn't be told from a caught breakage. Nothing was measured.", 2
    if not chosen:
        return "\n".join(notes), 2
    results: list[tuple[str, str, dict]] = []
    for path, mutant in chosen:
        results.append((_OUTCOMES.get(_try_mutant(copy, path, mutant, command, timeout), "error"), path, mutant))
        lost = _undo_side_effects(root, copy, listing, path)
        if lost:  # the copy can't be put back exactly, so the unmodified tests have to pass on it again before anything else counts
            again, _ = _run_tests(command, copy, timeout)
            notes.append(f"Breaking {path}:{mutant['line']} let the tests change {', '.join(lost[:5])}, which couldn't be copied back, so the unmodified tests ran again: {again}.")
            if again != "passed":
                results += [("error", *item) for item in chosen[len(results):]]  # what's left would run on a copy the tests fail on
                break
            listing = _listing(copy)
    out, code = _report(results, possible, timeout)
    return "\n".join([out[0], *notes, *out[1:]]), 2 if unknown else code


# ---------------------------------------------------------------- gate


_NOT_COLLECTED_FOLDERS = {"node_modules", "build", "dist", "venv", "env", "CVS", "_darcs"}


def _collected_test_file(path: str) -> bool:
    """Whether pytest's or unittest's default discovery would read this file. A project can configure others, and then this reads as a blocker to escalate."""
    *folders, name = path.split("/")
    named_as_a_test = name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py") or name in ("test.py", "tests.py"))
    return named_as_a_test and not any(folder.startswith(".") or folder in _NOT_COLLECTED_FOLDERS for folder in folders)


def _moved_tests(root: Path, revision: str, changed: dict[str, set[int]], source: str, removed: list[str], renamed: dict[str, str], staged: bool = False) -> tuple[dict[str, int], int]:
    """Tests gone from `source` that another changed file gained, with their assertions, since splitting a file along a seam removes nothing.

    Only a file pytest collects counts, and `staged` asks what a commit would hold, where a destination left unstaged doesn't count. Also returns the skips in any new file that took some, which no other comparison sees.
    """
    moved: dict[str, int] = {}
    new_file_skips = 0
    for path in changed:
        if path == source or not is_test_path(path) or not _collected_test_file(path):
            continue
        shape = _test_shape((filesystem.file_at(root, "", path) if staged else filesystem.read_text(root / path)) or "")
        before = filesystem.file_at(root, revision, renamed.get(path, path))
        had = _test_shape(before) if before is not None else None
        gained = [test for test in removed if shape and test in shape["tests"] and not (had and test in had["tests"])]
        for test in gained:
            moved[test] = max(moved.get(test, 0), shape["tests"][test])
        if gained and before is None:
            new_file_skips += shape["skips"]
    return moved, new_file_skips


def _renamed_in_place(old: dict[str, int], new: dict[str, int], gone: list[str]) -> dict[str, int]:
    """A class renamed, or a test moved in or out of one, keeps its test: same name under a new owner, in the same file."""
    gained: dict[str, list[str]] = {}
    for name in sorted((name for name in new if name not in old), key=lambda name: new[name]):
        gained.setdefault(name.rsplit(".", 1)[-1], []).append(name)
    found = {}
    for name in sorted(gone, key=lambda name: -old[name]):  # strongest with strongest, so two renamed classes aren't compared across each other
        options = gained.get(name.rsplit(".", 1)[-1])
        if options:
            found[name] = new[options.pop()]
    return found


def _weakened_tests(root: Path, base: str | None, changed: dict[str, set[int]], deleted: list[str], renamed: dict[str, str]) -> list[dict]:
    """Compare each changed test file with its previous version: fewer assertions, new skips, tests removed. A rename or a move keeps its history."""
    revision = base or "HEAD"
    findings = []
    for path in deleted:
        if is_test_path(path) and language_of(path):
            findings += _deleted_test_file(root, revision, changed, path, renamed)
    for path, old_path in renamed.items():
        if is_test_path(old_path) and language_of(old_path) == "python" and _collected_test_file(old_path) and not (is_test_path(path) and _collected_test_file(path)) and (_test_shape(filesystem.file_at(root, revision, old_path) or "") or {}).get("tests"):
            findings.append({"rule": "test-weakened", "path": path, "line": 1, "message": f"Renamed from {old_path} to where a test run won't collect it."})
    for path in changed:
        if not is_test_path(path) or language_of(path) != "python":
            continue
        before = filesystem.file_at(root, revision, renamed.get(path, path))
        after = filesystem.read_text(root / path)
        if before is None:
            continue
        if after is None:  # swapped for a link, or grown past what's read: its tests can't be shown to still be there
            if (_test_shape(before) or {}).get("tests"):
                findings.append({"rule": "test-weakened", "path": path, "line": 1, "message": "This test file can no longer be read, as a link or past the size limit, so nothing shows its tests are still there."})
            continue
        old, new = _test_shape(before), _test_shape(after)
        if old is None or new is None:
            continue
        removed = sorted(set(old["tests"]) - set(new["tests"]))
        moved, moved_skips = _moved_tests(root, revision, changed, path, removed, renamed) if removed else ({}, 0)
        moved.update(_renamed_in_place(old["tests"], new["tests"], [name for name in removed if name not in moved]))
        gone = [name for name in removed if name not in moved]
        if gone:
            findings.append({"rule": "test-weakened", "path": path, "line": 1, "message": f"Removed tests: {', '.join(gone[:5])}."})
        kept = {**moved, **new["tests"]}
        for name, count in old["tests"].items():
            if name in kept and kept[name] < count:
                findings.append({"rule": "test-weakened", "path": path, "line": new["lines"].get(name, 1), "message": f"{name} went from {count} assertions to {kept[name]}."})
        if new["skips"] + moved_skips > old["skips"]:
            findings.append({"rule": "test-weakened", "path": path, "line": 1, "message": f"{new['skips'] + moved_skips - old['skips']} new skips."})
    return findings


def _deleted_test_file(root: Path, revision: str, changed: dict[str, set[int]], path: str, renamed: dict[str, str]) -> list[dict]:
    """A deleted test file removes nothing if its tests all went somewhere that runs them, as an even split does."""
    before = filesystem.file_at(root, revision, path)
    old = _test_shape(before) if before is not None and language_of(path) == "python" else None
    if not old or not old["tests"]:
        return [{"rule": "test-weakened", "path": path, "line": 1, "message": "This test file was deleted."}]
    moved, moved_skips = _moved_tests(root, revision, changed, path, sorted(old["tests"]), renamed)
    gone = sorted(name for name, count in old["tests"].items() if moved.get(name, -1) < count)
    found = [{"rule": "test-weakened", "path": path, "line": 1, "message": f"This test file was deleted, and these tests didn't move: {', '.join(gone[:5])}."}] if gone else []
    if moved_skips > old["skips"]:
        found.append({"rule": "test-weakened", "path": path, "line": 1, "message": f"{moved_skips - old['skips']} new skips where its tests went."})
    return found


def _decorator_name(decorator: ast.AST) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else ""


def _is_fixture(node) -> bool:
    return any(_decorator_name(decorator) in ("fixture", "yield_fixture") for decorator in node.decorator_list)


def _opted_out(body: list) -> bool:
    """`__test__ = False`, which tells pytest not to collect what's beside it."""
    for node in body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__test__" for target in node.targets):
            return isinstance(node.value, ast.Constant) and not node.value.value
    return False


def _statements(body: list) -> Iterator:
    """A module's own statements, including those under a condition that can hold, since `if False:` and a helper's inner def never run as tests."""
    for node in body:
        if isinstance(node, ast.If):
            if not (isinstance(node.test, ast.Constant) and not node.test.value):
                yield from _statements(node.body)
            yield from _statements(node.orelse)
        elif isinstance(node, ast.Try):
            yield from _statements(node.body)
            yield from _statements(node.orelse)
        else:
            yield node


def _collected_tests(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    """What a test run would collect: `test*` functions, and their like in `Test*` classes and TestCases. Named with the class, since two classes can each have a test_run."""
    if _opted_out(tree.body):
        return
    yield from _tests_in(tree.body, "")


def _tests_in(body: list, prefix: str) -> Iterator[tuple[str, ast.AST]]:
    for node in _statements(body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test") and not _is_fixture(node):
            yield prefix + node.name, node
        # A base could be a TestCase by way of a project's own class, which can't be told from here, so only a class with none is certainly not collected.
        elif isinstance(node, ast.ClassDef) and not _opted_out(node.body) and (node.name.startswith("Test") or any(not (isinstance(base, ast.Name) and base.id == "object") for base in node.bases)):
            yield from _tests_in(node.body, f"{prefix}{node.name}.")


_NOT_RUNNING = re.compile(r"(?:skip|skipif|skip[A-Z_]\w*|importorskip|xfail|expectedFailure|SkipTest)$")
_TEST_RUNNERS = {"pytest", "mark", "unittest", "self", "cls"}


def _is_a_skip(node: ast.AST) -> bool:
    """A name in the code that stops a test running. `reader.skip_header()` is only a method, so an attribute counts on a test runner alone."""
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and bool(_NOT_RUNNING.match(node.id))
    if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load) or not _NOT_RUNNING.match(node.attr):
        return False
    owner = node.value
    return (owner.attr if isinstance(owner, ast.Attribute) else owner.id if isinstance(owner, ast.Name) else "") in _TEST_RUNNERS


def _test_shape(text: str) -> dict | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    tests: dict[str, int] = {}
    lines: dict[str, int] = {}
    for name, node in _collected_tests(tree):
        tests[name] = sum(1 for inner in ast.walk(node) if isinstance(inner, ast.Assert) or (isinstance(inner, ast.Call) and re.match(r"assert|raises", getattr(inner.func, "attr", getattr(inner.func, "id", "")) or "")))
        lines[name] = node.lineno
    # Names in the code, so a comment or a string neither counts as a skip nor cancels one, and skipif and importorskip do count.
    skips = sum(1 for node in ast.walk(tree) if _is_a_skip(node))
    return {"tests": tests, "lines": lines, "skips": skips}


def _new_definitions(root: Path, base: str | None, changed: dict[str, set[int]], renamed: dict[str, str]) -> list[tuple[str, str, int]]:
    """Top-level functions and classes that this change adds, in Python files. A moved file is compared with where it was."""
    revision = base or "HEAD"
    added = []
    for path in changed:
        if language_of(path) != "python" or is_test_path(path):
            continue
        text = filesystem.read_text(root / path)
        if text is None:
            continue
        before = filesystem.file_at(root, revision, renamed.get(path, path)) or ""
        try:
            new_tree, old_tree = ast.parse(text), ast.parse(before)
        except SyntaxError:
            continue
        old_names = {n.name for n in old_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        for node in new_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name not in old_names:
                added.append((node.name, path, node.lineno, _unread_parameters(node)))
    return added


def _unread_parameters(node: ast.AST) -> list[str]:
    """Parameters a new function never reads: options nobody needed yet. A decorated function's signature may be fixed by what calls it,
    and a stub reads nothing by design, so neither counts, and neither does `_name`, `*args`, `**kwargs` or a body using `locals()`."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.decorator_list:
        return []
    body = node.body[1:] if ast.get_docstring(node) is not None else node.body
    if all(isinstance(s, (ast.Pass, ast.Raise)) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) for s in body):
        return []
    read = {n.id for s in body for n in ast.walk(s) if isinstance(n, ast.Name)}
    if read & {"locals", "vars"}:
        return []
    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    return [a.arg for a in arguments if a.arg not in read and not a.arg.startswith("_") and a.arg not in ("self", "cls")]


def _reuse_candidates(project, name: str, own_path: str) -> list[str]:
    words = set(reuse._expand(reuse._words(name)))
    target_words = reuse._words(name)
    hits = []
    for symbol, path, line, kind, _ in reuse._symbols(project):
        if path == own_path or kind == "method" or is_test_path(path):
            continue
        symbol_words = reuse._words(symbol)
        if not symbol_words or len(symbol_words) < 2 and len(target_words) >= 2:
            continue
        overlap = sum(word in words for word in symbol_words) / max(len(symbol_words), len(target_words))
        if overlap >= 0.66:
            hits.append(f"{path}:{line} {symbol}")
    return hits[:3]


def _changed_for_gate(root: Path, base: str | None, paths: list[str] | None) -> dict[str, set[int]] | None:
    """What this change touches: named paths, or the diff. Generated files in the diff aren't the change."""
    if paths:
        return {name: set() for name in filesystem.list_files(root, paths, filesystem.load_config(root))}
    changed = filesystem.changed_lines(root, base)
    if changed is None:
        return None
    for path in filesystem.staged_differently(root):
        changed.setdefault(path, set())
    return {path: lines for path, lines in changed.items() if not filesystem.is_generated_output(path)}


def _for_design_notes(root: Path, base: str | None, changed: dict, paths: list[str] | None, gone: tuple[str, ...]) -> tuple[dict, tuple[str, ...]]:
    """`gate <path>` names what to look at, and naming a file doesn't change it. The design doc's notes speak of this change, so they need the diff, within what was named."""
    if not paths:
        return changed, gone
    if not filesystem.in_git(root):
        return {}, ()
    named = [design._relative(root, path) for path in paths]

    def within(path: str) -> bool:
        return "." in named or any(design._covers(folder, path) for folder in named if folder)

    deleted, renamed = filesystem.removed_and_renamed(root, base)
    diff = filesystem.changed_lines(root, base) or {}
    return ({path: lines for path, lines in diff.items() if within(path) or path in design.FILE_NAMES}, (*[path for path in deleted if within(path)], *[old for new, old in renamed.items() if within(new) or within(old)]))


def _breakage_elsewhere(root: Path, base: str | None, findings: list[dict], changed: dict, deleted: list[str]) -> list[dict]:
    """Unchanged files that now reach for something this change removed. These are the change's fault even though the diff doesn't show them.

    An edit to a file doesn't make an import of it this change's fault if the name it wants wasn't there before either.
    """
    gone = {Path(path).stem for path in deleted if Path(path).stem != "__init__"}
    # A package's __init__ goes by its folder: "pkg/__init__.py defines no 'helper'".
    edited = {Path(path).parent.name if Path(path).stem == "__init__" else Path(path).stem: path for path in changed if Path(path).stem != "__init__" or Path(path).parent.name}
    blamed = []
    for finding in findings:
        if finding["rule"] not in ("phantom-local-import", "phantom-import") or finding["path"] in changed:
            continue
        words = set(re.findall(r"\w+", finding["message"]))  # "core.py defines no 'total'", or "'utils.helper' isn't a module"
        if gone & words:
            blamed.append(finding)
            continue
        quoted = re.search(r"'([^']+)'", finding["message"])
        for stem in edited.keys() & words:
            wanted = [word for word in re.findall(r"\w+", quoted.group(1) if quoted else "") if word != stem]
            before = filesystem.file_at(root, base or "HEAD", edited[stem]) if wanted else None
            if before is None or any(re.search(rf"\b{re.escape(word)}\b", before) for word in wanted):
                blamed.append(finding)
                break
    return blamed


def _staged_findings(root: Path, changed: dict, base: str | None, renamed: dict[str, str], only: set[str] | None = None) -> list[dict]:
    """What a commit would contain may not be what's on disk, so read the staged version of files where the two differ, the files the
    scanner reads for secrets alone included. Only what the change added, as for what's on disk, and with paths named, only theirs."""
    found = []
    for path in filesystem.staged_differently(root):
        if not (language_of(path) or reads_only_for_secrets(path)) or (only is not None and path not in only):
            continue
        text = filesystem.file_at(root, "", path)
        if text is None:
            continue
        new = scanner.new_against_base(root, scanner.filter_findings(scanner.scan_text(path, text)), base, renamed)
        found += [{**f, "message": f"In the staged version, which differs from the file on disk: {f['message']}"} for f in new]
        found += _weakened_in_the_index(root, base, changed, path, text, renamed)
    return found


def _weakened_in_the_index(root: Path, base: str | None, changed: dict, path: str, staged: str, renamed: dict[str, str]) -> list[dict]:
    """A test taken out in the index and put back on disk would otherwise go unseen until the commit lands."""
    if not is_test_path(path) or language_of(path) != "python":
        return []
    before = filesystem.file_at(root, base or "HEAD", renamed.get(path, path))
    old, new = (_test_shape(before), _test_shape(staged)) if before is not None else (None, None)
    if not old or not new:
        return []
    moved, _ = _moved_tests(root, base or "HEAD", changed, path, sorted(set(old["tests"]) - set(new["tests"])), renamed, staged=True)
    moved.update(_renamed_in_place(old["tests"], new["tests"], [name for name in old["tests"] if name not in new["tests"] and name not in moved]))
    kept = {**moved, **new["tests"]}
    weakened = [name for name, count in old["tests"].items() if kept.get(name, -1) < count]
    described = [*([f"fewer or weaker tests: {', '.join(weakened[:5])}"] if weakened else []), *([f"{new['skips'] - old['skips']} new skips"] if new["skips"] > old["skips"] else [])]
    return [{"rule": "test-weakened", "path": path, "line": 1, "severity": "high", "confidence": "high", "category": "testing", "tier": "C", "score": 8.0, "layer": "test", "fix": "", "evidence": "", "id": "",
             "message": f"In the staged version, which differs from the file on disk: {message}."} for message in described]


def _sort_gate_findings(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    blockers, warnings = [], []
    for finding in findings:
        serious = finding["severity"] in ("critical", "high") and finding["confidence"] == "high"
        (blockers if finding["rule"] in _BLOCKING or finding["rule"] == "test-weakened" or serious else warnings).append(finding)
    return blockers, warnings


def _concern_detail(label: str, blocked: list[dict], warned: list[dict]) -> list[str]:
    lines = [f"{'FAIL' if blocked else 'warn'}  {label}"]
    lines += [f"  ! {f['path']}:{f['line']}  {f['rule']}: {f['message']}" for f in blocked[:8]]
    lines += [f"  - {f['path']}:{f['line']}  {f['rule']}: {f['message']}" for f in warned[:4]]
    hidden = max(0, len(blocked) - 8) + max(0, len(warned) - 4)
    return [*lines, f"  ... and {hidden} more."] if hidden else lines


def _concern_lines(blockers: list[dict], warnings: list[dict], not_checked: tuple = ()) -> list[str]:
    lines = []
    categories = {f.get("category") for f in blockers + warnings}
    for category, label in _CONCERNS:
        if category in categories:
            lines += _concern_detail(label, [f for f in blockers if f.get("category") == category], [f for f in warnings if f.get("category") == category])
    clean = [label for category, label in _CONCERNS if category not in categories and category not in ("notebook", "docs", *not_checked)]  # neither applies to most changes
    if clean:
        lines.append(f"ok    No automated finding: {', '.join(clean)}. That's not proof, since these checks can't see everything.")
    return lines


def _gate_findings(root: Path, base, changed, deleted, renamed, paths, result) -> list[dict]:
    """What this change introduced, including what a diff shows and a scan of the final files can't."""
    visible = scanner.filter_findings(result.findings, "medium")
    # Comment leads are low confidence across a whole repository, but on lines just written they're cheap to check and only ever warn.
    in_changed_files = [f for f in visible if f["path"] in changed] + [f for f in result.findings if f["path"] in changed and f.get("category") == "comments" and f["confidence"] == "low"]
    findings = in_changed_files if paths else scanner.new_against_base(root, in_changed_files, base, renamed)
    for extra in _weakened_tests(root, base, changed, deleted, renamed):
        findings.append({**extra, "severity": "high", "confidence": "high", "category": "testing", "tier": "C", "score": 8.0, "layer": "test", "fix": "", "evidence": "", "id": ""})
    findings += _breakage_elsewhere(root, base, visible, changed, [*deleted, *renamed.values()])
    # It decides what this gate reads, so a change can't clear itself with it, whether or not git shows the edit or the paths named include it.
    if filesystem.in_git(root) and filesystem.parse_config(filesystem.file_at(root, base or "HEAD", filesystem.CONFIG_NAME)) != filesystem.load_config(root):
        findings.append({"rule": "gate-config-changed", "path": ".occam.json", "line": 1, "message": "This change edits .occam.json, which decides what the scanner and this gate read, so their result here can't be taken at face value. A person should see this.",
                         "severity": "high", "confidence": "high", "category": "testing", "tier": "C", "score": 8.0, "layer": "test", "fix": "", "evidence": "", "id": ""})
    return findings + _staged_findings(root, changed, base, renamed, set(changed) if paths else None)


def _unread(changed, result) -> list[str]:
    analyzed = set(result.project.languages) - set(result.stats["unscanned"]) - set(result.stats["generated"])
    return [path for path in changed if language_of(path) and path not in analyzed]


def _unwatched(root: Path, paths) -> list[str]:
    """Files git was told not to watch, among the named paths when there are some."""
    hidden = filesystem.marked_unchanged(root)
    named = [str(Path(path).resolve().relative_to(root.resolve())).replace(os.sep, "/") for path in paths or []]
    return [name for name in hidden if not named or any(name == path or name.startswith(path.rstrip("/") + "/") or path == "." for path in named)]


def _not_checked(root: Path, paths, unread: list[str], result) -> list[str]:
    """What the report has to say wasn't checked. Silence here would read as clean."""
    lines: list[str] = []
    if unread:
        lines += ["", "NOT CHECKED, so say so in your report: " + ", ".join(unread[:8]) + " couldn't be read or are marked generated."]
    if result.stats.get("config_ignored") or result.stats.get("config_disabled") or result.stats.get("suppressed_inline"):
        lines += ["", "Silenced here: " + " ".join(report.exemptions({k: v for k, v in result.stats.items() if k.startswith(("config", "suppressed"))}))]
    submodules = filesystem.submodule_paths(root)
    if submodules:
        lines += ["", "NOT CHECKED: nothing inside submodules was read, because a submodule's git config could run programs: " + ", ".join(submodules[:8])]
    unwatched = _unwatched(root, paths)
    if unwatched:
        lines += ["", "NOT CHECKED: git has been told not to watch " + ", ".join(unwatched[:8]) + ", so edits there don't show."]
    return lines


def gate(root: Path, base: str | None = None, strict: bool = False, paths: list[str] | None = None, seconds: int | None = None) -> tuple[str, int]:
    """A skeptical read of this change. Blockers must be resolved or escalated before claiming it's done."""
    started = time.monotonic()
    missing = [path for path in paths or [] if not Path(path).exists()]
    if missing:
        return (f"No such path: {', '.join(missing)}. Nothing was checked.", 2)
    try:
        base = filesystem.fork_point(root, base)
        changed = _changed_for_gate(root, base, paths)
        if changed is None:
            return ("Not a git repository, so there's no diff to read. Name what you changed: `occam gate path ...`.", 2)
        deleted, renamed = ([], {}) if paths else filesystem.removed_and_renamed(root, base)
        for_design, gone = _for_design_notes(root, base, changed, paths, (*deleted, *renamed.values()))
    except (filesystem.GitProblem, filesystem.OutsideProject) as error:
        return (f"{error}. Nothing was checked." if not str(error).endswith("checked.") else str(error), 2)
    if not changed and not deleted:
        if paths:
            return (f"Nothing matched {', '.join(paths)}, so nothing was checked. A folder git ignores isn't read unless its files are named.", 2)
        unwatched = filesystem.marked_unchanged(root)
        return (f"No changes to gate, compared with {base or 'HEAD'}. If the work is already committed, pass --base with where it started." +
                (f" NOT CHECKED: git has been told not to watch {', '.join(unwatched[:5])}, so edits there don't show." if unwatched else ""), 1 if strict and unwatched else 0)
    result = scanner.run_scan(root, paths or None, seconds=seconds, focus=sorted(changed))
    findings = _gate_findings(root, base, changed, deleted, renamed, paths, result)
    whole = not result.stats.get("partial")
    # With a limit, the command line stops everything at it plus 35 seconds, so leave room for the rest. Without one, something else decides on the answer, so it's whole.
    budget = float("inf") if seconds is None else max(0.0, min(change_checks.RUNTIME_LIMIT, seconds + 10 - (time.monotonic() - started)))
    change_notes, change_not_run = ([], []) if paths else change_checks.notes(root, base, changed, deleted, renamed, whole, budget=budget)
    blockers, warnings = _sort_gate_findings(findings)
    extras = _gate_extras(root, base, changed, renamed, result.project, gone, for_design, whole=whole)
    warnings += change_notes
    blockers += [w for w in extras["warnings"] if w.get("blocks")]
    warnings += [w for w in extras["warnings"] if not w.get("blocks")]
    scope = None if paths else surgical.review(root, base, changed, result)
    if scope:
        orphaned = {(note["path"], note["line"]) for note in scope["notes"] if note["rule"] == "orphaned-by-change"}
        warnings = [w for w in warnings if not (w["rule"] in ("unreferenced-def", "orphan-module") and (w["path"], w["line"]) in orphaned)] + scope["notes"]
    lines = [f"occam gate: {len(changed)} changed files, {len(deleted)} deleted, {len(blockers)} blockers, {len(warnings)} warnings.", *report.partial_note(result.stats), *([scope["size"]] if scope and scope["size"] else []), "",
             *_concern_lines(blockers, warnings, (() if scope else ("scope",)) + (("change",) if change_not_run or paths else ()))]
    unread = _unread(changed, result)
    lines += _not_checked(root, paths, unread, result)
    if change_not_run:
        lines += ["", "NOT CHECKED, because the change is too large, time ran out or something couldn't be read: " + ", ".join(change_not_run) + "."]
    elif paths:
        lines += ["", "NOT CHECKED: what the change reaches elsewhere in the repository, which needs the diff. Run `gate` without paths for that."]
    lines += ["", "Checks only you can make:", *[f"  ? {question}" for question in [*_JUDGMENT, *_instructions_question(root, changed)]]]
    goal_line = _goal_line(root)
    if goal_line:
        lines += ["", goal_line]
    goal_broken = "  VIOLATED: " in goal_line  # a constraint the user stated, broken, isn't ready whatever else passes
    # Strict also stops on what couldn't be seen: drift from the goal's scope, a goal check that didn't run (except the API, which
    # `goal verify` compares), and files git was told not to watch.
    goal_open = any(marker in goal_line for marker in ("  DRIFT: ", "  NOT CHECKED: ", "Goal constraints NOT CHECKED"))
    if extras["others"]:
        lines += ["", extras["others"]]
    failed = bool(blockers) or goal_broken or (strict and bool(warnings or unread or goal_open or _unwatched(root, paths)))
    lines += ["", "NOT READY: fix these, or escalate each with a reason." if failed else "Automated checks are clear for what they could read. Finish the questions above, then report what you checked and what you didn't."]
    return "\n".join(lines), 1 if failed else 0


def _gate_extras(root: Path, base, changed, renamed: dict[str, str], project, gone: tuple[str, ...], for_design: dict, whole: bool = True) -> dict:
    warnings: list[dict] = []
    counts = project.identifier_counts
    for name, path, line, unread in _new_definitions(root, base, changed, renamed):
        if whole and counts.get(name, 0) <= 1 and not name.startswith("_") and not re.search(r"^(main|cli)$", name):
            warnings.append({"rule": "unreferenced-def", "path": path, "line": line, "message": f"New {name} has no callers. A function nothing calls isn't a feature.", "category": "dead-code"})
        if unread:
            warnings.append({"rule": "unread-parameter", "path": path, "line": line, "message": f"New {name} never reads {', '.join(unread[:4])}. Drop what nothing needs yet.", "category": "overengineering"})
        for hit in _reuse_candidates(project, name, path):
            warnings.append({"rule": "parallel-verbs", "path": path, "line": line, "message": f"New {name} may duplicate {hit}. Check it before keeping both.", "category": "duplication"})
            break
    warnings += design.gate_notes(root, base or "HEAD", for_design, gone)
    documents = [p for p in changed if docs.is_markdown(p) and p not in design.FILE_NAMES]  # design.gate_notes knows which of its parts needn't match the code
    if documents:
        warnings += docs.fact_findings(root, documents)
    warnings += _untested_change(changed)
    manifest_changes = [p for p in changed if manifests.DEPENDENCY_FILE.search(p)]
    if manifest_changes:
        added = _added_dependencies(root, base, changed, gone)
        said = f"This adds {', '.join(added[:6])}{' and more' if len(added) > 6 else ''}." if added else "Manifest changed."
        warnings.append({"rule": "unused-dependency", "path": manifest_changes[0], "line": 1, "message": f"{said} Check each new dependency exists and is the one meant with `occam deps --online --name ...`, and say why the existing options didn't fit.", "category": "bloat"})
    others = ""
    active = active_claims(root)
    claims = {path: claim_holder(active, path) for path in changed if claim_holder(active, path)}
    if claims:
        # gate doesn't know who runs it, so it names each holder rather than calling every claim another agent's
        others = ("Claimed files in this diff: " + ", ".join(f"{p} (by {o})" for p, o in sorted(claims.items())[:8])
                  + ". A claim that isn't yours means its holder may be editing that file, so check with them first.")
    return {"warnings": warnings, "others": others}


def _untested_change(changed) -> list[dict]:
    """Source changed and no test did. On a security or money path it blocks, the owner's call on 2026-11-08; elsewhere it warns."""
    source = [p for p in changed if language_of(p) in ("python", "javascript", "typescript", "go", "rust", "java", "kotlin") and not is_test_path(p)]
    if not source or any(is_test_path(p) for p in changed):
        return []
    risky = [p for p in source if _SECURITY_OR_MONEY.search(p)]
    if not risky:
        return [{"rule": "module-untested", "path": source[0], "line": 1, "message": f"{len(source)} source files changed and no test did. Say why that's fine, or add one.", "category": "testing"}]
    return [{"rule": "module-untested", "path": risky[0], "line": 1, "blocks": True, "category": "testing",
             "message": f"{', '.join(risky[:3])} handle{'s' if len(risky) == 1 else ''} security or money, changed, and no test did. Add a test that fails without the change, or escalate with a reason."}]


def _added_dependencies(root: Path, base: str | None, changed: dict, gone: tuple[str, ...]) -> list[str]:
    try:
        return new_dependencies(root, base or "HEAD", sorted(changed), gone)
    except (OSError, ValueError):  # outside git, or git can't say: the note stays general
        return []


def _instructions_question(root: Path, changed: dict) -> list[str]:
    """Instruction files in the folders holding this change, which can set rules a diff has to keep."""
    folders = {"."} | {str(parent) for path in changed for parent in Path(path).parents}
    found = sorted({str(Path(folder) / name) for folder in folders for name in _INSTRUCTION_FILES if (root / folder / name).is_file()})
    return [f"Did you follow what {', '.join(found[:6])} ask of these files?"] if found else []


def _goal_line(root: Path) -> str:
    try:
        with database(root) as db:
            row = db.execute("SELECT value FROM kv WHERE key = 'goal'").fetchone()
        state = json.loads(row[0]) if row else None
        if state is None:
            return "No goal recorded. For nontrivial work, `occam goal init` records what done means."
        total = len(state["requirements"])
        verified = sum(1 for r in state["requirements"] if r["status"] == "verified")
        line = f"Goal: {verified} of {total} requirements last verified. Run `occam goal verify` on the final state. Constraints to reread: {len(state['constraints'])}."
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):  # a damaged goal store shouldn't stop the gate, or read as blockers
        return ""
    try:  # against the goal's own base, which a gate run with --base doesn't change
        problems = scope_problems(root, state, None, costly=False) if state.get("constraints") or state.get("scope") else []
    except (OSError, ValueError, TypeError, KeyError) as error:  # GitProblem is a ValueError
        problems = [f"Goal constraints NOT CHECKED: {error}"]
    return "\n".join([line, *(f"  {problem}" for problem in problems)])
