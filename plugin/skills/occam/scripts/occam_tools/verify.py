"""Evidence instead of claims: did behavior change, can the tests fail, how does it grow, and is this change really done?"""

from __future__ import annotations

import ast
import difflib
import json
import math
import os
import platform
import re
import shlex
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from . import change_checks, design, docs, files as filesystem, report, reuse, scan as scanner, surgical
from .source import is_test_path, language_of
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


# ---------------------------------------------------------------- golden master


def _golden_path(root: Path, name: str) -> Path:
    folder = filesystem.state_dir(root) / "golden"
    folder.mkdir(exist_ok=True)
    return folder / (re.sub(r"[^\w.-]", "_", name) + ".json")


class CommandFailed(Exception):
    """The command couldn't run at all, which is different from running and failing."""


def _run_for_golden(root: Path, command: list[str], timeout: int) -> dict:
    try:
        done = filesystem.run_bounded(command, root, timeout)
    except subprocess.TimeoutExpired as error:
        raise CommandFailed(f"It didn't finish in {timeout}s.") from error
    except OSError as error:
        raise CommandFailed(f"It couldn't start: {error}.") from error
    # Exact bytes, so `\\r\\n` becoming `\\n` or one invalid byte becoming another still reads as a change.
    return {"exit": done.returncode, "stdout": done.stdout.decode("utf-8", "backslashreplace"), "stderr": done.stderr.decode("utf-8", "backslashreplace")}


def _normalize(output: dict, patterns: list[str]) -> dict:
    cleaned = dict(output)
    for key in ("stdout", "stderr"):
        for pattern in patterns:
            cleaned[key] = re.sub(pattern, "<normalized>", cleaned[key])
    return cleaned


def golden_record(root: Path, name: str, command: list[str], timeout: int, patterns: list[str]) -> tuple[str, int]:
    if not command:
        return "Give the command after --.", 2
    try:
        for pattern in patterns:
            re.compile(pattern)
    except re.error as error:
        return f"--normalize {pattern!r} isn't a valid expression: {error}.", 2
    try:
        first = _normalize(_run_for_golden(root, command, timeout), patterns)
        second = _normalize(_run_for_golden(root, command, timeout), patterns)
    except CommandFailed as error:
        return f"Not recorded. {error}", 2
    if first != second:
        return ("This command isn't deterministic: two runs differ. Fix the seed or clock, or blank the varying parts with --normalize. Not recorded.", 1)
    _golden_path(root, name).write_text(json.dumps({"command": command, "patterns": patterns, "result": first}))
    caution = ""
    if first["exit"]:
        caution = f" It exits {first['exit']}, so this records a failure, and a later match won't show it works."
    elif not first["stdout"] and not first["stderr"]:
        caution = " It prints nothing, so a later match will say very little."
    elif ran_no_tests(first["stdout"] + "\n" + first["stderr"]):
        caution = " It ran zero tests, so a later match won't show anything works."
    return f"Recorded '{name}': exit {first['exit']}, {len(first['stdout'])} bytes of output, identical across two runs.{caution}", 0


def golden_check(root: Path, name: str, timeout: int) -> tuple[str, int]:
    path = _golden_path(root, name)
    if not path.exists():
        return f"No recording named '{name}'.", 2
    recorded = json.loads(path.read_text())
    try:
        current = _normalize(_run_for_golden(root, recorded["command"], timeout), recorded.get("patterns", []))
    except CommandFailed as error:
        return f"'{name}' couldn't be checked. {error}", 2
    if current == recorded["result"]:
        failing = f" It was already exiting {current['exit']} when recorded, so this doesn't show it works." if current["exit"] else ""
        return f"'{name}' unchanged: same exit code and output.{failing}", 0
    lines = [f"'{name}' CHANGED."]
    if current["exit"] != recorded["result"]["exit"]:
        lines.append(f"Exit {recorded['result']['exit']} became {current['exit']}.")
    for stream in ("stdout", "stderr"):
        diff = list(difflib.unified_diff(recorded["result"][stream].splitlines(), current[stream].splitlines(), "recorded", "current", lineterm="", n=1))
        lines += diff[:40]
    if len(lines) == 1:
        lines.append("Only line endings or other invisible characters differ.")
    return "\n".join(lines), 1


# ---------------------------------------------------------------- mutation


_FLIPS = {ast.Eq: "!=", ast.NotEq: "==", ast.Lt: ">=", ast.LtE: ">", ast.Gt: "<=", ast.GtE: "<", ast.Is: "is not", ast.IsNot: "is", ast.In: "not in", ast.NotIn: "in"}
_OP_TEXT = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in"}
_ARITHMETIC = {ast.Add: ("+", "-"), ast.Sub: ("-", "+"), ast.Mult: ("*", "+"), ast.Div: ("/", "*")}


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
        if isinstance(node.value, int) and node.value in (0, 1):
            return node.col_offset, str(node.value), str(node.value + 1), f"{node.value} to {node.value + 1}"
    if isinstance(node, ast.Return) and node.value is not None and node.end_lineno == node.lineno and not (isinstance(node.value, ast.Constant) and node.value.value is None):
        value = source_lines[node.lineno - 1].encode()[node.value.col_offset:node.value.end_col_offset].decode("utf-8", "replace")
        return node.value.col_offset, value, "None", "return None instead"
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
    for name in filesystem.tracked_files(root) or filesystem.list_files(root):
        source = root / name
        target = destination / name
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _run_tests(command: str, cwd: Path, timeout: int) -> tuple[str, str]:
    existing = os.environ.get("PYTHONPATH", "")
    search = os.pathsep.join(filter(None, [str(cwd), str(cwd / "src"), existing]))
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": search}
    try:
        done = filesystem.run_bounded(shlex.split(command), cwd, timeout, env=environment)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except (OSError, ValueError) as error:
        return "failed", str(error)
    return ("passed" if done.returncode == 0 else "failed"), done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")


def _tests_really_use(copy: Path, path: str, command: str, timeout: int) -> bool:
    """Make the file impossible to import. If the tests still pass, they aren't testing this copy of it, whether from an editable install or by not importing it."""
    target = copy / path
    original = target.read_bytes()
    target.write_text("raise ImportError('occam: is this the file the tests import?')\n")
    outcome, _ = _run_tests(command, copy, timeout)
    target.write_bytes(original)
    return outcome != "passed"


def _choose_mutants(root: Path, targets, changed: bool, base, limit: int) -> list[tuple[str, dict]]:
    changed_map = filesystem.changed_lines(root, base) if (changed or base) else None
    candidates = filesystem.list_files(root, targets, filesystem.load_config(root))
    if changed_map is not None:
        candidates = [path for path in candidates if path in changed_map]
    mutants: list[tuple[str, dict]] = []
    untracked = set((filesystem.run_git(root, "ls-files", "-o", "--exclude-standard", "-z") or "").split("\0")) if changed_map is not None else set()
    for path in candidates:
        if language_of(path) == "python" and not is_test_path(path):
            text = filesystem.read_text(root / path) or ""
            lines = changed_map.get(path) if changed_map is not None else None
            # An untracked file is all new, which an empty set marks. On a tracked file it means the change only deleted lines, so there's nothing to mutate.
            if changed_map is None or lines or path in untracked:
                mutants += [(path, mutant) for mutant in _mutants(text, lines or None)]
    return mutants


def _try_mutant(copy: Path, path: str, mutant: dict, command: str, timeout: int) -> str:
    target = copy / path
    original = target.read_bytes()  # the mutant's columns came from filesystem.read_text, which is how this reads the file again
    lines = original.decode("utf-8", "replace").split("\n")
    line = lines[mutant["line"] - 1]
    lines[mutant["line"] - 1] = line[:mutant["start"]] + mutant["new"] + line[mutant["start"] + len(mutant["old"]):]
    target.write_text("\n".join(lines), encoding="utf-8")
    outcome, _ = _run_tests(command, copy, timeout)
    target.write_bytes(original)
    return outcome


def mutate(root: Path, command: str, targets: list[str] | None, changed: bool, base: str | None, limit: int, timeout: int) -> tuple[str, int]:
    """Break the code on purpose, in a temporary copy, and see whether the tests notice. The working tree isn't touched."""
    if not command.strip():
        return "Give the test command with --cmd.", 2
    if needs_a_shell(command):
        return f"That test command {NEEDS_A_SHELL}", 2
    mutants = _choose_mutants(root, targets, changed, base, limit)
    if not mutants:
        return "No mutation points in Python source there. For other languages: Stryker (JS/TS), cargo-mutants (Rust), go-mutesting (Go), PIT (JVM).", 2
    chosen = mutants[::max(1, len(mutants) // limit)][:limit]
    survivors = []
    with tempfile.TemporaryDirectory(prefix="occam-mutate-") as folder:
        copy = Path(folder)
        _copy_project(root, copy)
        baseline, output = _run_tests(command, copy, timeout)
        if baseline != "passed":
            return f"The tests don't pass on an unmodified copy ({baseline}), so mutation would mean nothing.\n{output[-800:]}", 2
        if ran_no_tests(output):
            return "That command ran zero tests.", 2
        usable = {path: _tests_really_use(copy, path, command, timeout) for path in {path for path, _ in chosen}}
        unused = sorted(path for path, used in usable.items() if not used)
        chosen = [item for item in chosen if usable[item[0]]]
        again, _ = _run_tests(command, copy, timeout)
        if again != "passed":  # the copy is reused, so a test that leaves something behind or is flaky would look like it caught every breakage
            return f"The tests passed once on an unmodified copy, then {again} when run again. They leave something behind or they're flaky, so a failure couldn't be told from a caught breakage. Nothing was measured.", 2
        for path, mutant in chosen:
            if _try_mutant(copy, path, mutant, command, timeout) == "passed":
                survivors.append((path, mutant))
    caught = len(chosen) - len(survivors)
    out = [f"{caught} of {len(chosen)} deliberate breakages were caught ({len(mutants)} possible, sampled evenly). Ran in a temporary copy, and your files weren't touched."]
    if unused:
        out.append("Not measured, because the tests still pass when these can't even be imported. Either no test imports them, or the tests import an installed copy: " + ", ".join(unused[:10]))
    if not chosen:
        return "\n".join(out[1:]), 2
    if survivors:
        out.append("The tests still pass with these changes, so nothing protects this behavior:")
        # The line as it was when mutated, since a run can take minutes and someone may have edited the file since.
        out += [f"  {path}:{m['line']}  {m['what']}  ->  {m['source'].strip()[:90]}" for path, m in survivors[:25]]
        out.append("Some survivors are equivalent or unimportant. Judge each, and add a test for those that matter.")
    return "\n".join(out), 1 if survivors else 0


# ---------------------------------------------------------------- bench


def _measure(command: list[str], timeout: int) -> tuple[float, float, int]:
    """Wall seconds, peak RSS in MB and exit code of one fresh process."""
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = started + timeout
    while True:
        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if pid:
            break
        if time.perf_counter() > deadline:
            process.kill()
            os.wait4(process.pid, 0)
            raise subprocess.TimeoutExpired(command, timeout)
        time.sleep(0.005)
    elapsed = time.perf_counter() - started
    process.returncode = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (status >> 8)
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return elapsed, usage.ru_maxrss / divisor, process.returncode


def _slope(xs: list[float], ys: list[float]) -> float | None:
    """Least-squares exponent of y = a + b * x^k, trying several startup costs `a` and keeping the straightest fit in log space.

    Assuming nearly all of the smallest run is startup would make plain linear work with none read as quadratic.
    """
    if sum(1 for x, y in zip(xs, ys) if x > 0 and y - 0.95 * min(ys) > 0.02) < 2:
        return None
    best: tuple[float, float] | None = None
    for share in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        floor = share * min(ys)
        pairs = [(math.log(x), math.log(y - floor)) for x, y in zip(xs, ys) if x > 0 and y - floor > 0.02]
        if len(pairs) < 2:
            continue
        mean_x = statistics.mean(p[0] for p in pairs)
        mean_y = statistics.mean(p[1] for p in pairs)
        across = sum((p[0] - mean_x) ** 2 for p in pairs)
        spread = sum((p[1] - mean_y) ** 2 for p in pairs)
        if not across:
            continue
        slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pairs) / across
        straightness = round(slope ** 2 * across / spread, 3) if spread else 1.0
        if best is None or straightness > best[0]:  # a tie keeps the smaller startup cost, the plainer reading
            best = (straightness, slope)
    return best[1] if best else None


def _bench_rows(template: str, sizes: list[int], repeat: int, timeout: int) -> list[tuple]:
    """(size, median seconds, spread, peak MB, status) for each size, stopping at the first that fails."""
    rows = []
    for size in sorted(sizes):
        command = shlex.split(template.replace("{n}", str(size)))
        times, memory = [], []
        status = "ok"
        for _ in range(repeat):
            try:
                elapsed, rss, code = _measure(command, timeout)
            except subprocess.TimeoutExpired:
                status = "timed out"
                break
            except OSError as error:
                status = f"couldn't start: {error.strerror}"
                break
            if code != 0:
                status = f"exit {code}"
                break
            times.append(elapsed)
            memory.append(rss)
        if status != "ok":
            rows.append((size, None, None, None, status))
            break
        rows.append((size, statistics.median(times), max(times) - min(times), max(memory), status))
    return rows


def _growth_line(done: list[tuple]) -> tuple[str, bool]:
    """Describe how time grew. True if it's worse than linear."""
    sizes = [float(r[0]) for r in done]
    time_growth = _slope(sizes, [r[1] for r in done])
    if time_growth is None:
        return f"Not enough signal to fit growth: the largest run took {done[-1][1]:.3f}s, mostly startup. Use larger sizes.", False
    memory_growth = _slope(sizes, [r[3] for r in done])
    shape = "about linear or better" if time_growth < 1.25 else "superlinear" if time_growth < 1.8 else "about quadratic or worse"
    memory = f" Peak memory grows like n^{memory_growth:.2f}." if memory_growth is not None else " Peak memory stayed about flat."
    return f"Time grows like n^{time_growth:.2f}: {shape}.{memory}", time_growth >= 1.25


def _limit_line(limit: float, value: float, size: int) -> tuple[str, bool]:
    if value > limit:
        return f"Time limit {limit}s EXCEEDED: {value:.2f}s at n={size}.", True
    headroom = limit / value if value else float("inf")
    return f"Time limit {limit}s: measured {value:.2f}s at n={size}, {headroom:.1f}x headroom.", False


def bench(template: str, sizes: list[int], repeat: int, limit_seconds: float | None, timeout: int) -> tuple[str, int]:
    if "{n}" not in template:
        return "The command needs {n} where the size goes.", 2
    try:
        shlex.split(template)
    except ValueError as error:
        return f"That command can't be read: {error}.", 2
    rows = _bench_rows(template, sizes, repeat, timeout)
    done = [r for r in rows if r[4] == "ok"]
    out = [f"{os.cpu_count()} CPUs, {platform.system()} {platform.machine()}, Python {platform.python_version()}. Each row: {repeat} fresh processes, median time and largest peak RSS.",
           f"{'size':>12}{'seconds':>10}{'spread':>9}{'peak MB':>10}  status"]
    for size, seconds, spread, rss, status in rows:
        out.append(f"{size:>12}" + (f"{seconds:>10.3f}{spread:>9.3f}{rss:>10.1f}" if status == "ok" else f"{'-':>10}{'-':>9}{'-':>10}") + f"  {status}")
    failed = len(done) != len(rows)
    if len(done) >= 2:
        line, worse = _growth_line(done)
        out.append(line)
        failed = failed or worse
    if done and limit_seconds is not None:
        line, exceeded = _limit_line(limit_seconds, done[-1][1], done[-1][0])
        out.append(line)
        failed = failed or exceeded
    out.append("Evidence label: local measurement, this machine and this data. It says how it grew here, not what production capacity is. Check the output is still correct too.")
    return "\n".join(out), 2 if any(row[4].startswith("couldn't start") for row in rows) else 1 if failed else 0


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


def _new_definitions(root: Path, base: str | None, changed: dict[str, set[int]]) -> list[tuple[str, str, int]]:
    """Top-level functions and classes that this change adds, in Python files."""
    revision = base or "HEAD"
    added = []
    for path in changed:
        if language_of(path) != "python" or is_test_path(path):
            continue
        text = filesystem.read_text(root / path)
        if text is None:
            continue
        before = filesystem.file_at(root, revision, path) or ""
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


def _staged_findings(root: Path, changed: dict, base: str | None, renamed: dict[str, str]) -> list[dict]:
    """What a commit would contain may not be what's on disk, so read the staged version of files where the two differ. Only what the change added, as for what's on disk."""
    found = []
    for path in filesystem.staged_differently(root):
        if not language_of(path):
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
    if filesystem.in_git(root) and (filesystem.file_at(root, base or "HEAD", ".occam.json") or "") != (filesystem.read_text(root / ".occam.json") or ""):
        findings.append({"rule": "gate-config-changed", "path": ".occam.json", "line": 1, "message": "This change edits .occam.json, which decides what the scanner and this gate read, so their result here can't be taken at face value. A person should see this.",
                         "severity": "high", "confidence": "high", "category": "testing", "tier": "C", "score": 8.0, "layer": "test", "fix": "", "evidence": "", "id": ""})
    if not paths:
        findings += _staged_findings(root, changed, base, renamed)
    return findings


def _unread(changed, result) -> list[str]:
    analyzed = set(result.project.languages) - set(result.stats["unscanned"]) - set(result.stats["generated"])
    return [path for path in changed if language_of(path) and path not in analyzed]


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
    unwatched = [] if paths else filesystem.marked_unchanged(root)
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
                (f" NOT CHECKED: git has been told not to watch {', '.join(unwatched[:5])}, so edits there don't show." if unwatched else ""), 0)
    result = scanner.run_scan(root, paths or None, seconds=seconds, focus=sorted(changed))
    findings = _gate_findings(root, base, changed, deleted, renamed, paths, result)
    whole = not result.stats.get("partial")
    # With a limit, the command line stops everything at it plus 35 seconds, so leave room for the rest. Without one, something else decides on the answer, so it's whole.
    budget = float("inf") if seconds is None else max(0.0, min(change_checks.RUNTIME_LIMIT, seconds + 10 - (time.monotonic() - started)))
    change_notes, change_not_run = ([], []) if paths else change_checks.notes(root, base, changed, deleted, renamed, whole, budget=budget)
    blockers, warnings = _sort_gate_findings(findings)
    extras = _gate_extras(root, base, changed, result.project, gone, for_design, whole=whole)
    warnings += change_notes
    warnings += extras["warnings"]
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
    if extras["others"]:
        lines += ["", extras["others"]]
    failed = bool(blockers) or goal_broken or (strict and bool(warnings or unread))
    lines += ["", "NOT READY: fix these, or escalate each with a reason." if failed else "Automated checks are clear for what they could read. Finish the questions above, then report what you checked and what you didn't."]
    return "\n".join(lines), 1 if failed else 0


def _gate_extras(root: Path, base, changed, project, gone: tuple[str, ...], for_design: dict, whole: bool = True) -> dict:
    warnings: list[dict] = []
    counts = project.identifier_counts
    for name, path, line, unread in _new_definitions(root, base, changed):
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
    source_changed = [p for p in changed if language_of(p) in ("python", "javascript", "typescript", "go", "rust", "java", "kotlin") and not is_test_path(p)]
    tests_changed = [p for p in changed if is_test_path(p)]
    if source_changed and not tests_changed:
        warnings.append({"rule": "module-untested", "path": source_changed[0], "line": 1, "message": f"{len(source_changed)} source files changed and no test did. Say why that's fine, or add one.", "category": "testing"})
    manifest_changes = [p for p in changed if re.search(r"(^|/)(pyproject\.toml|requirements[^/]*\.txt|package\.json|Cargo\.toml|go\.mod|setup\.py)$", p)]
    if manifest_changes:
        added = _added_dependencies(root, base, changed, gone)
        said = f"This adds {', '.join(added[:6])}{' and more' if len(added) > 6 else ''}." if added else "Manifest changed."
        warnings.append({"rule": "unused-dependency", "path": manifest_changes[0], "line": 1, "message": f"{said} Check each new dependency exists and is the one meant with `occam deps --online --name ...`, and say why the existing options didn't fit.", "category": "bloat"})
    others = ""
    active = active_claims(root)
    claims = {path: claim_holder(active, path) for path in changed if claim_holder(active, path)}
    if claims:
        others = "Other agents hold claims on files in this diff: " + ", ".join(f"{p} ({o})" for p, o in sorted(claims.items())[:8])
    return {"warnings": warnings, "others": others}


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
