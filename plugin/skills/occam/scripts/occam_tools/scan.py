"""The scanner: analyze each file (in parallel, with a content cache), run cross-file passes, then filter and rank."""

from __future__ import annotations

import ast
import hashlib
import json
import multiprocessing
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import VERSION, clones, files as filesystem, imports, rules_config, rules_py, rules_shell, rules_text, source as src
from .catalog import BY_ID, CONFIDENCES
from .project import Project

SEVERITY_WEIGHT = {"critical": 16, "high": 8, "medium": 3, "low": 1}
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.25}
_IGNORE = re.compile(r"occam:\s*ignore(?:\[([\w, -]+)\])?")
_PARALLEL_FROM = 150
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}\.[\w.-]{1,63}")
_OUTPUT_SAMPLE = 200_000
GOD_FILE_LINES = 1000  # pylint's max-module-lines default, shared with occam-python's guidance
# A shell tool usually gives a command two minutes, and a scan it kills returns nothing, while reading less only costs what the next run picks up.
# Measured under heavy load, 90 here finished within 10 to 30 seconds of the kill, too close.
DEFAULT_SECONDS = 75
# Past this, reading everything just to give a named folder its context stops fitting in those two minutes (measured: 195,312 files took 51 s warm, about 3 times that cold, 5 GB).
LARGE_REPOSITORY_FILES = 50_000
_BATCH_FILES = 1024
_BATCH_BYTES = 6_000_000  # the limit is checked between batches, and analysis runs at very roughly 400 KB per CPU second
_MAX_CACHE_BYTES = 2_000_000_000  # about 22 million lines. It can always be rebuilt, and nothing else ever shrinks it
_CACHE_SCHEMA = f"{VERSION}-10-py{sys.version_info.major}.{sys.version_info.minor}"  # what parses, and what the standard library has, varies by interpreter
_PARSER_LANGUAGES = {"python", "notebook"}


def _normal_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:240]


def fingerprint(rule: str, path: str, evidence: str, ordinal: int = 0) -> str:
    """Stable across line moves: rule, file, and the text of the line."""
    key = f"{rule}\0{path}\0{_normal_line(evidence)}\0{ordinal}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _safe_evidence(rule: str, text_line: str) -> str:
    """Results get saved, printed and pasted, so a secret's line is kept only as a hash, which still gives the finding a stable identity."""
    if rule == "hardcoded-secret" or rules_text.has_secret_shape(text_line) or rules_text.has_secret_assignment(text_line):
        return "withheld:" + hashlib.sha1(text_line.encode("utf-8", "replace")).hexdigest()[:16]
    return _normal_line(text_line)


def _shape(rule: str, path: str, line: int, message: str | None, overrides: dict, text_line: str, cell: int | None = None) -> dict:
    definition = BY_ID[rule]
    finding = {"rule": rule, "path": path, "line": line, "message": message or definition.title, "evidence": _safe_evidence(rule, text_line)}
    if cell is not None:
        finding["cell"] = cell
    finding.update({key: value for key, value in overrides.items() if key in ("severity", "confidence", "related", "owner")})
    return finding


def _suppressed(source: src.Source, rule: str, line: int) -> bool:
    for candidate in (line, line - 1):
        text = source.line_text(candidate)
        if "occam:" in text:
            match = _IGNORE.search(text)
            if match and (match.group(1) is None or rule in [part.strip() for part in match.group(1).split(",")]):
                return True
    return False


def analyze_text(path: str, text: str, language: str | None = None) -> dict:
    """Everything one file contributes. Pure: same path and text, same result."""
    language = language or src.language_of(path, text[:200])
    record: dict = {"path": path, "language": language, "findings": [], "facts": {}, "lines": text.count("\n") + 1, "parse_error": None}
    is_test = src.gets_test_checks(path)
    is_script = src.is_script_path(path)
    if language == "notebook":
        return _analyze_notebook(path, text, record, is_test, is_script)
    if language is None:
        if src.reads_only_for_secrets(path):
            _analyze_for_secrets(path, text, record)
        return record
    if src.looks_generated(text):
        record["generated"] = True
        return record
    source = src.load(path, text, language)
    raw: list[tuple] = list(rules_text.text_findings(source, is_test, is_script))
    raw += _rules_for_what_runs(path, text, language, is_test)
    if language == "shell":
        raw = rules_shell.outside_heredocs(text, raw)
    if language == "python":
        comment_lines = {line for line, _ in source.comments}
        found, facts, error = rules_py.analyze(text, path, source.code, comment_lines, is_test, is_script)
        raw += found
        record["facts"] = facts
        record["parse_error"] = error
        if error:
            raw.append(("unparseable", 1, f"This doesn't parse on Python {sys.version_info.major}.{sys.version_info.minor}: {error[:120]}", {}))
    else:
        structured, facts = rules_text.structure_findings(source, is_test)
        raw += structured
        facts["imports"] = rules_text.import_facts(source)
        record["facts"] = facts
    _finish_record(record, source, raw)
    return record


def _rules_for_what_runs(path: str, text: str, language: str, is_test: bool) -> list[tuple]:
    found = list(rules_config.terraform_findings(text)) if language == "terraform" else []
    found += rules_config.migration_findings(path, text)
    found += [] if is_test else rules_config.login_without_a_limit(text, language)
    return found + ([] if is_test else list(rules_config.hidden_characters(text)))


def _analyze_for_secrets(source_path: str, text: str, record: dict) -> None:
    """A config file or Dockerfile. It stays language-less, so nothing else treats it as code, and stats say it was read for this and nothing more."""
    record["secrets_only"] = True
    record["lines"] = 0
    if src.is_fixture_path(source_path):
        return
    source = src.load(source_path, text, "shell" if src.DOCKERFILE.search(source_path) else None)
    for rule, line, message, overrides in [*rules_text.secrets_only_findings(source), *rules_config.findings(source_path, text)]:
        if _suppressed(source, rule, line):
            record["suppressed"] = record.get("suppressed", 0) + 1
        else:
            record["findings"].append(_shape(rule, source_path, line, message, overrides, source.line_text(line)))


def _finish_record(record: dict, source: src.Source, raw: list[tuple], cell_of=None) -> None:
    path = record["path"]
    seen = set()
    for rule, line, message, overrides in raw:
        if _suppressed(source, rule, line):
            record["suppressed"] = record.get("suppressed", 0) + 1
            continue
        key = (rule, line, message)
        if key in seen:
            continue
        seen.add(key)
        finding = _shape(rule, path, line, message, overrides, source.line_text(line))
        if cell_of:
            cell, inner = cell_of(line)
            finding["cell"], finding["line"] = cell, inner
        record["findings"].append(finding)
    if source.language in ("python", "notebook") or source.language in rules_text.C_FAMILY or source.language in ("shell", "ruby", "sql"):
        table, _ = clones.line_table(source.code)
        record["line_table"] = table
        record["fingerprints"] = clones.fingerprints(table)
    record["identifiers"] = rules_text.identifiers(source.text)
    total = len(source.line_starts)
    if total > GOD_FILE_LINES and not src.gets_test_checks(path) and not cell_of:
        record["findings"].append(_shape("god-file", path, 1, f"{total} lines in one file.", {"severity": "high"} if total > 3 * GOD_FILE_LINES else {}, source.line_text(1)))


def _analyze_notebook(path: str, text: str, record: dict, is_test: bool, is_script: bool) -> dict:
    try:
        notebook = src.load_notebook(text)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        record["parse_error"] = f"{type(error).__name__}: {error}"
        return record
    source = src.load(path, notebook.python, "python")
    comment_lines = {line for line, _ in source.comments}
    raw: list[tuple] = list(rules_text.text_findings(source, is_test, True))
    found, facts, error = rules_py.analyze(notebook.python, path, source.code, comment_lines, is_test, True, notebook=True)
    raw += found
    record["facts"] = facts
    record["parse_error"] = error

    def cell_of(line: int) -> tuple[int, int]:
        if 1 <= line <= len(notebook.line_map):
            return notebook.line_map[line - 1]
        return (0, line)

    raw = [item for item in raw if item[0] not in ("undefined-name", "commented-out-code")]
    _finish_record(record, source, raw, cell_of)
    record["findings"] += _notebook_findings(notebook, path)
    return record


def _run_by_this_cell(loads: dict[str, int], callable_so_far: dict[str, dict[str, int]]) -> dict[str, int]:
    """What a cell reads, including what the functions it reaches read. Each is reported at the line that reached it."""
    found = dict(loads)
    pending = [(name, line) for name, line in loads.items() if name in callable_so_far]
    seen = set()
    while pending:
        name, line = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for read in callable_so_far[name]:
            found.setdefault(read, line)
            if read in callable_so_far:
                pending.append((read, line))
    return found


def _notebook_findings(notebook: src.Notebook, path: str) -> list[dict]:
    findings = []
    counts = [cell["execution_count"] for cell in notebook.cells if cell["execution_count"] is not None]
    if counts and counts != sorted(counts):
        findings.append(_shape("nb-out-of-order", path, 1, f"Execution counts run {counts[:8]}.", {}, ""))
    defined: set[str] = set()
    later: dict[str, int] = {}
    per_cell = []
    for cell in notebook.cells:
        loads, stores, reads = _cell_names(cell["source"])
        per_cell.append((cell["number"], loads, stores, reads))
        for name in stores:
            later.setdefault(name, cell["number"])
    import builtins
    known = set(dir(builtins)) | {"get_ipython", "display", "In", "Out", "_", "__"}
    callable_so_far: dict[str, dict[str, int]] = {}
    for number, loads, stores, reads in per_cell:
        callable_so_far.update(reads)
        for name, line in _run_by_this_cell(loads, callable_so_far).items():
            if name not in defined and name not in stores and name not in known and later.get(name, 0) > number:
                findings.append({**_shape("nb-hidden-state", path, line, f"'{name}' is used here but only defined in cell {later[name]}.", {}, ""), "cell": number})
        defined |= set(stores)
    for cell in notebook.cells:
        for index, line in enumerate(cell["source"].split("\n"), start=1):
            match = re.match(r"\s*[!%]\s*pip\s+install\s+(.*)", line)
            if match and not re.search(r"==|-r\s|\.txt", match.group(1)):
                findings.append({**_shape("nb-unpinned-install", path, index, None, {}, line), "cell": cell["number"]})
    for number, text in notebook.output_text_by_cell.items():
        sample = text[:_OUTPUT_SAMPLE]
        emails = set(_EMAIL.findall(sample))
        if len(emails) >= 2 or rules_text.has_secret_shape(sample):
            findings.append({**_shape("nb-sensitive-output", path, 1, f"Cell {number}'s stored output has {len(emails)} email addresses or a credential.", {}, ""), "cell": number})
    for number, size in notebook.raw_size_by_cell.items():
        if size > 500_000:
            findings.append({**_shape("nb-large-output", path, 1, f"Cell {number} stores {size // 1000} KB of output.", {}, ""), "cell": number})
    return findings


def _cell_names(cell_source: str) -> tuple[dict, set, dict]:
    """What a cell reads as it runs, what it defines, and what each thing it defines reads only once it's called."""
    cleaned = "\n".join(re.sub(r"^(\s*)[%!].*", r"\1pass", line) for line in cell_source.split("\n"))
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return {}, set(), {}
    loads: dict[str, int] = {}
    stores: set[str] = set()
    functions: dict[str, list] = {}
    pending = list(tree.body)
    while pending:  # outermost only. What's nested runs as part of whatever encloses it, and shares its names
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.ClassDef):  # a method can run from anything holding the class, and that can't be followed from here, so reaching the class counts them all
            functions.setdefault(node.name, []).extend(method for method in node.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)))
        else:
            pending.extend(ast.iter_child_nodes(node))
    deferred = {id(inner) for scope in ast.walk(tree) if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) for statement in scope.body for inner in ast.walk(statement)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in deferred:
            if isinstance(node.ctx, ast.Store):
                stores.add(node.id)
            else:
                loads.setdefault(node.id, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stores.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            stores.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            stores.add(node.name)
        elif isinstance(node, ast.Lambda):
            stores.update(a.arg for a in node.args.args)
        elif isinstance(node, ast.Global):
            stores.update(node.names)
    return loads, stores, {name: _reads_when_called(group) for name, group in functions.items()}


def _reads_when_called(functions: list) -> dict[str, int]:
    """What these bodies read from outside themselves."""
    reads: dict[str, int] = {}
    for function in functions:
        nodes = [node for statement in function.body for node in ast.walk(statement)]
        local = {node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        for scope in [function, *nodes]:
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                arguments = scope.args
                local.update(item.arg for item in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *filter(None, [arguments.vararg, arguments.kwarg])])
        reads.update({node.id: node.lineno for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in local})
    return reads


# ---------------------------------------------------------------- cache


def _lightened(record: dict) -> dict:
    """A record without what only the scan's own rules read, which is most of its size. Questions about a giant repository shouldn't need gigabytes."""
    for field in ("findings", "line_table", "fingerprints"):
        record.pop(field, None)
    return record


class Cache:
    """Per-file results keyed on content, in one sqlite file so concurrent agents can share it safely."""

    def __init__(self, state: Path | None) -> None:
        self.connection = None
        if state is None:
            return
        try:
            self.connection = sqlite3.connect(str(state / "cache.db"), timeout=10)
            self.connection.execute("CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, data BLOB)")
            self._trim()
        except (sqlite3.Error, OSError):
            self.connection = None

    def _trim(self) -> None:
        """Past the limit the oldest half goes. Freed pages get reused, so the file stops growing, and the repositories that fill this keep their recent progress."""
        pages, free, size = [self.connection.execute(pragma).fetchone()[0] for pragma in ("PRAGMA page_count", "PRAGMA freelist_count", "PRAGMA page_size")]
        if (pages - free) * size > _MAX_CACHE_BYTES:
            with self.connection:
                self.connection.execute("DELETE FROM files WHERE rowid IN (SELECT rowid FROM files ORDER BY rowid LIMIT (SELECT COUNT(*) / 2 FROM files))")

    def get_many(self, keys: list[str], light: bool = False) -> dict[str, dict]:
        if self.connection is None or not keys:
            return {}
        found: dict[str, dict] = {}
        try:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                marks = ",".join("?" * len(chunk))
                for key, data in self.connection.execute(f"SELECT key, data FROM files WHERE key IN ({marks})", chunk):  # occam: ignore[query-in-loop] sqlite limits bound variables, so this is the batch
                    found[key] = _lightened(json.loads(data)) if light else json.loads(data)
        except (sqlite3.Error, ValueError):
            return found
        return found

    def put_many(self, items: list[tuple[str, dict]]) -> None:
        if self.connection is None or not items:
            return
        try:
            with self.connection:
                self.connection.executemany("INSERT OR REPLACE INTO files VALUES (?, ?)", [(k, json.dumps(v)) for k, v in items])
        except sqlite3.Error:
            pass

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()


def _analyze_for_pool(item: tuple[str, str]) -> dict:
    path, text = item
    try:
        return analyze_text(path, text)
    except Exception as error:  # one strange file mustn't stop a whole scan, and it's reported as unchecked
        return {"path": path, "language": src.language_of(path), "findings": [], "facts": {}, "lines": text.count("\n") + 1, "parse_error": f"{type(error).__name__}: {error}"}


def _exit_with_parent() -> None:
    """A shell tool's timeout kills the scan but not its workers, which would otherwise wait forever for work, costing about 500 MB each time."""
    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch() -> None:
        parent.join()
        os._exit(1)

    threading.Thread(target=watch, daemon=True).start()


class _Workers:
    """One pool for a whole scan, started only if a batch is big enough to need it.

    Spawned workers put the working directory on sys.path, so a repository's multiprocessing.py would run. They start somewhere empty,
    and a worker can start at any point in the scan, so the process stays there until the pool has gone.
    """

    def __init__(self, count: int) -> None:
        self.count = count
        self.pool: ProcessPoolExecutor | None = None
        self.home = ""
        self.empty: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> _Workers:
        return self

    def __exit__(self, stopped_by, *_) -> None:
        if self.pool is not None:
            if stopped_by:  # nobody will read the answer, and a stuck file would keep a limit waiting past its own end
                for worker in list((getattr(self.pool, "_processes", None) or {}).values()):
                    worker.terminate()
            self.pool.shutdown(wait=not stopped_by, cancel_futures=True)
        if self.empty is not None:
            if self.home:
                os.chdir(self.home)
            self.empty.cleanup()

    def analyze(self, pending: list[tuple[str, str]]) -> list[dict]:
        if self.pool is None and (self.count <= 1 or len(pending) < _PARALLEL_FROM):
            return [_analyze_for_pool(item) for item in pending]
        try:
            if self.pool is None:
                self.home = os.getcwd()
                self.empty = tempfile.TemporaryDirectory(prefix="occam-")
                os.chdir(self.empty.name)
                self.pool = ProcessPoolExecutor(max_workers=self.count, initializer=_exit_with_parent)
            return list(self.pool.map(_analyze_for_pool, pending, chunksize=32))
        except (OSError, RuntimeError):
            self.count = 0
            return [_analyze_for_pool(item) for item in pending]


# ---------------------------------------------------------------- scan


class ScanResult:
    def __init__(self, findings: list[dict], stats: dict, project: Project | None) -> None:
        self.findings = findings
        self.stats = stats
        self.project = project


def _reading_plan(root: Path, all_files: list[str], selected: list[str], scoped: bool, focus: list[str] | None, seconds: int | None) -> tuple[list[str], list[str], bool]:
    """What to read and in what order, what the scan then covers, and whether it had to narrow to that."""
    narrowed = bool(seconds) and len(all_files) > LARGE_REPOSITORY_FILES and (scoped or focus is not None)
    known = set(all_files)
    focus = [path for path in focus or [] if path in known]  # it orders what the scan covers and never widens it, so a vendored file stays unread and reported as such
    if narrowed and not scoped:
        selected = focus
    wanted = list(dict.fromkeys([*focus, *selected, *([] if narrowed else all_files)]))
    if seconds and len(wanted) > LARGE_REPOSITORY_FILES:
        activity = filesystem.churn(root, timeout=15)  # if time runs out, what people keep changing is the part worth having read
        wanted.sort(key=lambda path: -activity.get(path, 0))
    return wanted, selected, narrowed


def _what_was_missed(records: dict, wanted: list[str], selected: list[str], narrowed: bool, repository_files: int, seconds: int | None, deadline: float | None, saved: bool, rules_wanted: bool) -> dict | None:
    """None if everything asked for can run. The cross-file rules took about a fifth of what reading did on the largest tree measured, so they need some of the time left."""
    read_all = len(records) == len(wanted)
    in_time = not rules_wanted or deadline is None or time.monotonic() < deadline - (seconds or 0) / 4
    if read_all and not narrowed and in_time:
        return None
    return {"reason": "scope" if narrowed and read_all else "time", "read": len(records), "wanted": len(wanted), "repository_files": repository_files, "seconds": seconds, "saved": saved,
            "unread_in_scope": sum(1 for path in selected if path not in records)}


def _cache_folder(root: Path) -> Path | None:
    try:
        return filesystem.state_dir(root)
    except OSError:
        return None


def _findings(project: Project, records: dict, selected: set[str], config: dict, project_rules: bool, partial: dict | None) -> list[dict]:
    findings = [finding for path, record in records.items() if path in selected for finding in record["findings"]]
    for finding in project.run(enabled=project_rules, whole=partial is None):
        if finding["path"] in selected:
            finding.setdefault("evidence", "")
            findings.append(finding)
    findings = _apply_filters(project.refine(findings), config)
    _decorate(findings)
    return findings


def _stats(root: Path, records: dict, selected: list[str], selected_set: set[str], config: dict, isolated: bool, partial: dict | None, started: float) -> dict:
    chosen = [record for record in records.values() if record["path"] in selected_set]
    languages = Counter(record["language"] for record in chosen if record["language"])
    return {"isolated": isolated, "unscanned": sorted(path for path in selected if records.get(path, {}).get("unscanned")),
            "generated": sorted(record["path"] for record in chosen if record.get("generated")),
            "secrets_only": sorted(record["path"] for record in chosen if record.get("secrets_only")),
            "suppressed_inline": sum(records.get(path, {}).get("suppressed", 0) for path in selected), "partial": partial,
            "config_ignored": config.get("ignore", []), "config_disabled": config.get("disable", []),
            "files": len(selected), "analyzed": sum(1 for record in chosen if record["language"]), "lines": sum(record["lines"] for record in chosen if record["language"]),
            "languages": dict(languages), "seconds": round(time.time() - started, 2),
            "parse_errors": [(path, record["parse_error"]) for path, record in records.items() if record.get("parse_error")], "root": str(root),
            "not_parsed_languages": sorted(language for language in languages if language not in _PARSER_LANGUAGES)}


def run_scan(root: Path, targets: list[str] | None = None, changed_only: bool = False, base: str | None = None, use_cache: bool = True,
             workers: int | None = None, isolated: bool = False, seconds: int | None = None, focus: list[str] | None = None) -> ScanResult:
    """Scan the repository, or just what changed against base.

    Project-wide facts come from the whole repository, so a changed-only scan still knows about the code around it. That costs about 0.55 GB per million
    lines however little was asked for, so isolated reads only what was selected and leaves out the rules that need the rest.

    `seconds` asks for an answer in about that long, for a caller that would rather have part of one than none. Reading stops when it runs out, and
    on a very large repository anything scoped reads only its scope. Rules needing the rest of the repository then don't run, since they would call things
    unused or missing because of what wasn't read, and stats["partial"] says what happened. What was read stays cached, so the next run gets further. `focus`
    is read first, and is the scope of an unscoped scan that has to narrow. Callers needing a complete answer leave `seconds` out.
    """
    started = time.time()
    deadline = time.monotonic() + seconds if seconds else None
    config = filesystem.load_config(root)
    selected = filesystem.list_files(root, targets, config) if targets else filesystem.list_files(root, None, config)
    all_files = filesystem.list_files(root, None, config) if targets else selected
    project_rules = not isolated
    changed = filesystem.changed_lines(root, base) if (changed_only or base) else None
    if changed is not None:
        wanted = set(changed)
        selected = [path for path in selected if path in wanted]
    elif changed_only or base:
        raise filesystem.BadRevision("Not a git repository, so there's no diff to scan")
    all_files = selected if isolated else all_files
    cache = Cache(_cache_folder(root) if use_cache else None)
    wanted, selected, narrowed = _reading_plan(root, all_files, selected, bool(targets and len(selected) < len(all_files)) or changed is not None, focus, seconds)
    records = _analyze_all(root, wanted, cache, workers, deadline=deadline)
    cache.close()
    partial = _what_was_missed(records, wanted, selected, narrowed, len(all_files), seconds, deadline, use_cache, project_rules)
    # Cross-file rules credit a duplicate to the first file they meet, so results can't depend on what happened to be read first.
    records = {path: records[path] for path in dict.fromkeys([*all_files, *selected]) if path in records}
    # Unread files are still listed, because whether a name like .env is committed doesn't depend on reading it.
    project = Project(root, list(dict.fromkeys([*records, *(selected if partial else [])])))
    for record in records.values():
        project.add_file(record["path"], record)
    selected_set = set(selected)
    findings = _findings(project, records, selected_set, config, project_rules, partial)
    if changed is not None:
        findings = new_against_base(root, findings, base, filesystem.removed_and_renamed(root, base)[1])
    stats = _stats(root, records, selected, selected_set, config, isolated, partial, started)
    return ScanResult(findings, stats, project)


def _batches(root: Path, paths: list[str]):
    """Small enough in files and in bytes that a limit checked between them isn't overrun by much."""
    batch: list[str] = []
    size = 0
    for path in paths:
        batch.append(path)
        try:
            size += (root / path).stat().st_size
        except OSError:
            pass
        if len(batch) >= _BATCH_FILES or size >= _BATCH_BYTES:
            yield batch
            batch, size = [], 0
    if batch:
        yield batch


def _analyze_all(root: Path, paths: list[str], cache: Cache, workers: int | None, light: bool = False, deadline: float | None = None) -> dict[str, dict]:
    """Results go in the cache a batch at a time, because a scan killed by a shell tool's timeout must leave the next one further along."""
    root = Path(root).resolve()  # the workers' empty folder becomes the working directory
    records: dict[str, dict] = {}
    with _Workers(workers if workers is not None else (os.cpu_count() or 2)) as pool:
        for batch in _batches(root, paths):
            if deadline is not None and time.monotonic() > deadline:
                break
            records.update(_analyze_batch(root, batch, cache, pool, light))
    return records


def _analyze_batch(root: Path, paths: list[str], cache: Cache, pool: _Workers, light: bool) -> dict[str, dict]:
    records: dict[str, dict] = {}
    pending: list[tuple[str, str]] = []
    keys: dict[str, str] = {}
    texts: dict[str, str] = {}
    for path in paths:
        language = src.language_of(path)
        if language is None:
            head = _head(root / path)
            language = src.language_of(path, head)
        if language is None and not src.reads_only_for_secrets(path):
            records[path] = {"path": path, "language": None, "findings": [], "facts": {}, "lines": 0}
            continue
        text = filesystem.read_text(root / path)
        if text is None:
            records[path] = {"path": path, "language": None, "findings": [], "facts": {}, "lines": 0, "unscanned": True}
            continue
        key = hashlib.sha1(f"{_CACHE_SCHEMA}\0{path}\0".encode() + text.encode("utf-8", "replace")).hexdigest()
        keys[path] = key
        texts[path] = text
    cached = cache.get_many(list(keys.values()), light)
    for path, key in keys.items():
        if key in cached:
            records[path] = cached[key]
        else:
            pending.append((path, texts[path]))
    texts.clear()
    computed = pool.analyze(pending)
    cache.put_many([(keys[record["path"]], record) for record in computed])
    for record in computed:
        records[record["path"]] = _lightened(record) if light else record
    return records


def _head(path: Path) -> str:
    if not filesystem.is_plain_file(path):
        return ""
    try:
        with open(path, "rb") as handle:
            return handle.read(200).decode("utf-8", "replace")
    except OSError:
        return ""


def _apply_filters(findings: list[dict], config: dict) -> list[dict]:
    disabled = set(config.get("disable", []))
    return [finding for finding in findings if finding["rule"] not in disabled]


def new_against_base(root: Path, findings: list[dict], base: str | None, renamed: dict[str, str] | None = None) -> list[dict]:
    """Keep what the previous version of each file didn't have. A line number can't decide this: replacing a body with `pass` is reported on the unchanged def line."""
    revision = base or "HEAD"
    known: dict[str, set[str]] = {}
    kept = []
    for finding in findings:
        path = finding["path"]
        if not finding.get("evidence") and "cell" not in finding:
            kept.append(finding)  # a cross-file finding has no per-file history to compare with
            continue
        if path not in known:
            before = filesystem.file_at(root, revision, (renamed or {}).get(path, path))
            known[path] = {f["id"] for f in scan_text(path, before)} if before is not None else set()
        if finding["id"] not in known[path]:
            kept.append(finding)
    return kept


def _decorate(findings: list[dict]) -> None:
    """Fill in catalog fields, stable identity, and a rank."""
    ordinals: Counter = Counter()
    for finding in findings:
        rule = BY_ID[finding["rule"]]
        finding.setdefault("severity", rule.severity)
        finding.setdefault("confidence", rule.confidence)
        finding["category"] = rule.category
        finding["layer"] = rule.layer
        finding["tier"] = rule.tier
        finding["fix"] = rule.fix
        finding.setdefault("evidence", "")
        identity = f"{finding['rule']}\0{finding['path']}\0{finding['evidence'] or finding['message']}"
        finding["id"] = fingerprint(finding["rule"], finding["path"], finding["evidence"] or finding["message"], ordinals[identity])
        ordinals[identity] += 1
        finding["score"] = SEVERITY_WEIGHT[finding["severity"]] * CONFIDENCE_WEIGHT[finding["confidence"]]
    findings.sort(key=lambda f: (-f["score"], f["path"], f["line"]))


def filter_findings(findings: list[dict], min_confidence: str = "medium", rules: list[str] | None = None) -> list[dict]:
    confidence_cut = CONFIDENCES.index(min_confidence)
    return [f for f in findings if CONFIDENCES.index(f["confidence"]) <= confidence_cut and (not rules or f["rule"] in rules)]


def scan_text(path: str, text: str, language: str | None = None) -> list[dict]:
    """Scan one piece of code with no repository around it: a snippet, a cell, a hook's view of one file."""
    record = analyze_text(path, text, language)
    findings = _apply_filters(record["findings"], {})
    _decorate(findings)
    return findings


def scan_snippet(path: str, text: str, language: str | None = None) -> ScanResult:
    """A snippet or notebook cell given directly, including what can be checked about its imports."""
    record = analyze_text(path, text, language)
    project = Project(None, [path])
    project.add_file(path, record)
    findings = list(record["findings"])
    imports.python_imports(project)
    imports.stdlib_attributes(project)
    findings += [f for f in project.findings]
    findings = _apply_filters(findings, {})
    _decorate(findings)
    stats = {"files": 1, "analyzed": 1, "lines": record["lines"], "languages": {record["language"] or "unknown": 1}, "seconds": 0.0,
             "parse_errors": [(path, record["parse_error"])] if record.get("parse_error") else [], "root": "(snippet)",
             "not_parsed_languages": []}
    return ScanResult(findings, stats, project)

