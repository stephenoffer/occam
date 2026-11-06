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
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from . import docs, files as filesystem, report, reuse, scan as scanner, surgical
from .source import is_test_path, language_of
from .workflow import active_claims, claim_holder, database
from .zero_tests import ran_no_tests

_BLOCKING = {"truncation-marker", "fake-success", "stub-body", "stub-raise", "phantom-import", "phantom-local-import", "phantom-attribute", "undefined-name", "hardcoded-secret",
             "sql-injection", "shell-injection", "tls-disabled", "jwt-unverified", "fail-open", "swallowed-exception", "test-no-assert", "test-tautology", "test-focused", "mutable-default",
             "debug-leftover", "committed-secret-file", "unsafe-deserialize", "dynamic-eval"}
_CONCERNS = [
    ("incomplete", "Implementation is complete"), ("hallucination", "APIs and packages are real"), ("security", "Security"), ("error-masking", "Failures stay visible"),
    ("testing", "Tests can fail"), ("scope", "Stayed in scope"), ("complexity", "Complexity"), ("duplication", "No new duplication"), ("overengineering", "No needless structure"),
    ("dead-code", "No dead code left"), ("bloat", "No bloat"), ("comments", "Comments"), ("naming", "Naming"), ("performance", "Performance"),
    ("scalability", "Scalability"), ("architecture", "Architecture"), ("usability", "Usability"), ("reinvention", "Didn't reinvent"), ("language-practice", "Language practice"), ("notebook", "Notebooks"), ("docs", "Documents match the code"),
]
_JUDGMENT = [
    "Reread the original request. Is every part of it done, connected and reachable through the real entry point?",
    "Did you honor every constraint the user stated, including ones from earlier in the conversation?",
    "Did you check the layers this touches, and name the ones you didn't? (`occam map` lists them.)",
    "Is the behavior right for empty, huge, malformed and concurrent input, where those can occur?",
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
        done = subprocess.run(command, cwd=str(root), capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise CommandFailed(f"It didn't finish in {timeout}s.") from error
    except OSError as error:
        raise CommandFailed(f"It couldn't start: {error}.") from error
    return {"exit": done.returncode, "stdout": done.stdout, "stderr": done.stderr}


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
        first = _normalize(_run_for_golden(root, command, timeout), patterns)
        second = _normalize(_run_for_golden(root, command, timeout), patterns)
    except CommandFailed as error:
        return f"Not recorded. {error}", 2
    if first != second:
        return ("This command isn't deterministic: two runs differ. Fix the seed or clock, or blank the varying parts with --normalize. Not recorded.", 1)
    _golden_path(root, name).write_text(json.dumps({"command": command, "patterns": patterns, "result": first}))
    return f"Recorded '{name}': exit {first['exit']}, {len(first['stdout'])} bytes of output, identical across two runs.", 0


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
        return f"'{name}' unchanged: same exit code and output.", 0
    lines = [f"'{name}' CHANGED."]
    if current["exit"] != recorded["result"]["exit"]:
        lines.append(f"Exit {recorded['result']['exit']} became {current['exit']}.")
    for stream in ("stdout", "stderr"):
        diff = list(difflib.unified_diff(recorded["result"][stream].splitlines(), current[stream].splitlines(), "recorded", "current", lineterm="", n=1))
        lines += diff[:40]
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
        done = subprocess.run(shlex.split(command), cwd=str(cwd), capture_output=True, text=True, errors="replace", timeout=timeout, env=environment)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except (OSError, ValueError) as error:
        return "failed", str(error)
    return ("passed" if done.returncode == 0 else "failed"), done.stdout + done.stderr


def _tests_really_use(copy: Path, path: str, command: str, timeout: int) -> bool:
    """Make the file impossible to import. If the tests still pass, they aren't testing this copy of it, whether from an editable install or by not importing it."""
    target = copy / path
    original = target.read_text()
    target.write_text("raise ImportError('occam: is this the file the tests import?')\n")
    outcome, _ = _run_tests(command, copy, timeout)
    target.write_text(original)
    return outcome != "passed"


def _choose_mutants(root: Path, targets, changed: bool, base, limit: int) -> list[tuple[str, dict]]:
    changed_map = filesystem.changed_lines(root, base) if (changed or base) else None
    candidates = filesystem.list_files(root, targets, filesystem.load_config(root))
    if changed_map is not None:
        candidates = [path for path in candidates if path in changed_map]
    mutants: list[tuple[str, dict]] = []
    for path in candidates:
        if language_of(path) == "python" and not is_test_path(path):
            text = filesystem.read_text(root / path) or ""
            lines = changed_map.get(path) if changed_map is not None else None
            mutants += [(path, mutant) for mutant in _mutants(text, lines or None)]
    return mutants


def _try_mutant(copy: Path, path: str, mutant: dict, command: str, timeout: int) -> str:
    target = copy / path
    original = target.read_text()
    lines = original.split("\n")
    line = lines[mutant["line"] - 1]
    lines[mutant["line"] - 1] = line[:mutant["start"]] + mutant["new"] + line[mutant["start"] + len(mutant["old"]):]
    target.write_text("\n".join(lines))
    outcome, _ = _run_tests(command, copy, timeout)
    target.write_text(original)
    return outcome


def mutate(root: Path, command: str, targets: list[str] | None, changed: bool, base: str | None, limit: int, timeout: int) -> tuple[str, int]:
    """Break the code on purpose, in a temporary copy, and see whether the tests notice. The working tree isn't touched."""
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
    """Least-squares exponent of y = a * x^k, after removing fixed startup cost, using sizes where enough signal is left."""
    floor = 0.95 * min(ys)
    pairs = [(math.log(x), math.log(y - floor)) for x, y in zip(xs, ys) if x > 0 and y - floor > 0.02]
    if len(pairs) < 2:
        return None
    mean_x = statistics.mean(p[0] for p in pairs)
    mean_y = statistics.mean(p[1] for p in pairs)
    denominator = sum((p[0] - mean_x) ** 2 for p in pairs)
    return sum((p[0] - mean_x) * (p[1] - mean_y) for p in pairs) / denominator if denominator else None


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


def _limit_line(label: str, unit: str, limit: float, value: float, size: int) -> tuple[str, bool]:
    if value > limit:
        return f"{label} limit {limit}{unit} EXCEEDED: {value:.2f}{unit} at n={size}.", True
    headroom = limit / value if value else float("inf")
    return f"{label} limit {limit}{unit}: measured {value:.2f}{unit} at n={size}, {headroom:.1f}x headroom.", False


def bench(template: str, sizes: list[int], repeat: int, limit_seconds: float | None, limit_rss: float | None, timeout: int) -> tuple[str, int]:
    if "{n}" not in template:
        return "The command needs {n} where the size goes.", 2
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
    if done:
        for label, unit, limit, value in (("Time", "s", limit_seconds, done[-1][1]), ("Memory", " MB", limit_rss, done[-1][3])):
            if limit is not None:
                line, exceeded = _limit_line(label, unit, limit, value, done[-1][0])
                out.append(line)
                failed = failed or exceeded
    out.append("Evidence label: local measurement, this machine and this data. It says how it grew here, not what production capacity is. Check the output is still correct too.")
    return "\n".join(out), 1 if failed else 0


# ---------------------------------------------------------------- gate


def _weakened_tests(root: Path, base: str | None, changed: dict[str, set[int]], deleted: list[str], renamed: dict[str, str]) -> list[dict]:
    """Compare each changed test file with its previous version: fewer assertions, new skips, tests removed. A rename keeps its history."""
    revision = base or "HEAD"
    findings = []
    for path in deleted:
        if is_test_path(path) and language_of(path):
            findings.append({"rule": "test-weakened", "path": path, "line": 1, "message": "This test file was deleted."})
    for path in changed:
        if not is_test_path(path) or language_of(path) != "python":
            continue
        before = filesystem.file_at(root, revision, renamed.get(path, path))
        after = filesystem.read_text(root / path)
        if before is None or after is None:
            continue
        old, new = _test_shape(before), _test_shape(after)
        if old is None or new is None:
            continue
        removed = sorted(set(old["tests"]) - set(new["tests"]))
        if removed:
            findings.append({"rule": "test-weakened", "path": path, "line": 1, "message": f"Removed tests: {', '.join(removed[:5])}."})
        for name, count in old["tests"].items():
            if name in new["tests"] and new["tests"][name] < count:
                findings.append({"rule": "test-weakened", "path": path, "line": new["lines"].get(name, 1), "message": f"{name} went from {count} assertions to {new['tests'][name]}."})
        if new["skips"] > old["skips"]:
            findings.append({"rule": "test-weakened", "path": path, "line": 1, "message": f"{new['skips'] - old['skips']} new skips."})
    return findings


def _test_shape(text: str) -> dict | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    tests: dict[str, int] = {}
    lines: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            count = sum(1 for inner in ast.walk(node) if isinstance(inner, ast.Assert) or (isinstance(inner, ast.Call) and re.match(r"assert|raises", getattr(inner.func, "attr", getattr(inner.func, "id", "")) or "")))
            tests[node.name] = count
            lines[node.name] = node.lineno
    skips = len(re.findall(r"\bskip\b|\bxfail\b", text))
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
                added.append((node.name, path, node.lineno))
    return added


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


def _breakage_elsewhere(findings: list[dict], changed: dict, deleted: list[str]) -> list[dict]:
    """Unchanged files that now reach for something this change removed. These are the change's fault even though the diff doesn't show them."""
    stems = {Path(path).stem for path in [*changed, *deleted] if Path(path).stem != "__init__"}
    return [f for f in findings if f["rule"] in ("phantom-local-import", "phantom-import") and f["path"] not in changed and any(re.search(rf"\b{re.escape(stem)}\b", f["message"]) for stem in stems)]


def _staged_findings(root: Path, changed: dict) -> list[dict]:
    """What a commit would contain may not be what's on disk, so read the staged version of files where the two differ."""
    found = []
    for path in filesystem.staged_differently(root):
        if language_of(path):
            text = filesystem.run_git(root, "show", f":./{path}")
            if text is not None:
                found += [{**f, "message": f"In the staged version, which differs from the file on disk: {f['message']}"} for f in scanner.filter_findings(scanner.scan_text(path, text))]
    return found


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


def gate(root: Path, base: str | None = None, strict: bool = False, paths: list[str] | None = None) -> tuple[str, int]:
    """A skeptical read of this change. Blockers must be resolved or escalated before claiming it's done."""
    missing = [path for path in paths or [] if not Path(path).exists()]
    if missing:
        return (f"No such path: {', '.join(missing)}. Nothing was checked.", 2)
    try:
        base = filesystem.fork_point(root, base)
        changed = _changed_for_gate(root, base, paths)
        if changed is None:
            return ("Not a git repository, so there's no diff to read. Name what you changed: `occam gate path ...`.", 2)
        deleted, renamed = ([], {}) if paths else filesystem.removed_and_renamed(root, base)
    except (filesystem.GitProblem, filesystem.OutsideProject) as error:
        return (f"{error}. Nothing was checked." if not str(error).endswith("checked.") else str(error), 2)
    if not changed and not deleted:
        return ("No changes to gate.", 0)
    result = scanner.run_scan(root, paths) if paths else scanner.run_scan(root, None)
    visible = scanner.filter_findings(result.findings, "medium")
    in_changed_files = [f for f in visible if f["path"] in changed]
    findings = in_changed_files if paths else scanner.new_against_base(root, in_changed_files, base, renamed)
    for extra in _weakened_tests(root, base, changed, deleted, renamed):
        findings.append({**extra, "severity": "high", "confidence": "high", "category": "testing", "tier": "C", "score": 8.0, "layer": "test", "fix": "", "evidence": "", "id": ""})
    findings += _breakage_elsewhere(visible, changed, [*deleted, *renamed.values()])
    if not paths:
        findings += _staged_findings(root, changed)
    blockers, warnings = _sort_gate_findings(findings)
    extras = _gate_extras(root, base, changed, result.project)
    warnings += extras["warnings"]
    scope = None if paths else surgical.review(root, base, changed, result)
    if scope:
        orphaned = {(note["path"], note["line"]) for note in scope["notes"] if note["rule"] == "orphaned-by-change"}
        warnings = [w for w in warnings if not (w["rule"] in ("unreferenced-def", "orphan-module") and (w["path"], w["line"]) in orphaned)] + scope["notes"]
    lines = [f"occam gate: {len(changed)} changed files, {len(deleted)} deleted, {len(blockers)} blockers, {len(warnings)} warnings.", *([scope["size"]] if scope and scope["size"] else []), "",
             *_concern_lines(blockers, warnings, () if scope else ("scope",))]
    analyzed = set(result.project.languages) - set(result.stats["unscanned"]) - set(result.stats["generated"])
    unread = [path for path in changed if language_of(path) and path not in analyzed]
    if unread:
        lines += ["", "NOT CHECKED, so say so in your report: " + ", ".join(unread[:8]) + " couldn't be read or are marked generated."]
    if result.stats.get("config_ignored") or result.stats.get("config_disabled") or result.stats.get("suppressed_inline"):
        lines += ["", "Silenced here: " + " ".join(report.exemptions({k: v for k, v in result.stats.items() if k.startswith(("config", "suppressed"))}))]
    submodules = filesystem.submodule_paths(root)
    if submodules:
        lines += ["", "NOT CHECKED: nothing inside submodules was read, because a submodule's git config could run programs: " + ", ".join(submodules[:8])]
    lines += ["", "Checks only you can make:", *[f"  ? {question}" for question in _JUDGMENT]]
    goal_line = _goal_line(root)
    if goal_line:
        lines += ["", goal_line]
    if extras["others"]:
        lines += ["", extras["others"]]
    failed = bool(blockers) or (strict and bool(warnings or unread))
    lines += ["", "NOT READY: fix these, or escalate each with a reason." if failed else "Automated checks are clear for what they could read. Finish the questions above, then report what you checked and what you didn't."]
    return "\n".join(lines), 1 if failed else 0


def _gate_extras(root: Path, base, changed, project) -> dict:
    warnings: list[dict] = []
    counts = project.identifier_counts
    for name, path, line in _new_definitions(root, base, changed):
        if counts.get(name, 0) <= 1 and not name.startswith("_") and not re.search(r"^(main|cli)$", name):
            warnings.append({"rule": "unreferenced-def", "path": path, "line": line, "message": f"New {name} has no callers. A function nothing calls isn't a feature.", "category": "dead-code"})
        for hit in _reuse_candidates(project, name, path):
            warnings.append({"rule": "parallel-verbs", "path": path, "line": line, "message": f"New {name} may duplicate {hit}. Check it before keeping both.", "category": "duplication"})
            break
    documents = [p for p in changed if docs.is_markdown(p)]
    if documents:
        warnings += docs.fact_findings(root, documents)
    source_changed = [p for p in changed if language_of(p) in ("python", "javascript", "typescript", "go", "rust", "java", "kotlin") and not is_test_path(p)]
    tests_changed = [p for p in changed if is_test_path(p)]
    if source_changed and not tests_changed:
        warnings.append({"rule": "module-untested", "path": source_changed[0], "line": 1, "message": f"{len(source_changed)} source files changed and no test did. Say why that's fine, or add one.", "category": "testing"})
    manifest_changes = [p for p in changed if re.search(r"(^|/)(pyproject\.toml|requirements[^/]*\.txt|package\.json|Cargo\.toml|go\.mod|setup\.py)$", p)]
    if manifest_changes:
        warnings.append({"rule": "unused-dependency", "path": manifest_changes[0], "line": 1, "message": "Manifest changed. Check any new dependency with `occam deps --online --name ...`, and say why the existing options didn't fit.", "category": "bloat"})
    others = ""
    active = active_claims(root)
    claims = {path: claim_holder(active, path) for path in changed if claim_holder(active, path)}
    if claims:
        others = "Other agents hold claims on files in this diff: " + ", ".join(f"{p} ({o})" for p, o in sorted(claims.items())[:8])
    return {"warnings": warnings, "others": others}


def _goal_line(root: Path) -> str:
    try:
        with database(root) as db:
            row = db.execute("SELECT value FROM kv WHERE key = 'goal'").fetchone()
    except OSError:
        return ""
    if not row:
        return "No goal recorded. For nontrivial work, `occam goal init` records what done means."
    state = json.loads(row[0])
    total = len(state["requirements"])
    verified = sum(1 for r in state["requirements"] if r["status"] == "verified")
    return f"Goal: {verified} of {total} requirements last verified. Run `occam goal verify` on the final state. Constraints to reread: {len(state['constraints'])}."
