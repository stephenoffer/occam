"""The scanner: analyze each file (in parallel, with a content cache), run cross-file passes, then filter and rank."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import VERSION, clones, files as filesystem, imports, rules_py, rules_shell, rules_text, source as src
from .catalog import BY_ID, CONFIDENCES, SEVERITIES
from .project import Project

SEVERITY_WEIGHT = {"critical": 16, "high": 8, "medium": 3, "low": 1}
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.25}
_IGNORE = re.compile(r"occam:\s*ignore(?:\[([\w, -]+)\])?")
_PARALLEL_FROM = 150
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}\.[\w.-]{1,63}")
_OUTPUT_SAMPLE = 200_000
GOD_FILE_LINES = 1000  # pylint's max-module-lines default, shared with occam-python's guidance
_CACHE_SCHEMA = f"{VERSION}-3-py{sys.version_info.major}.{sys.version_info.minor}"  # what parses, and what the standard library has, varies by interpreter
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
    is_test = src.is_test_path(path)
    is_script = src.is_script_path(path)
    if language == "notebook":
        return _analyze_notebook(path, text, record, is_test, is_script)
    if language is None:
        return record
    if src.looks_generated(text):
        record["generated"] = True
        return record
    source = src.load(path, text, language)
    raw: list[tuple] = list(rules_text.text_findings(source, is_test, is_script))
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
    if total > GOD_FILE_LINES and not src.is_test_path(path) and not cell_of:
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


def _notebook_findings(notebook: src.Notebook, path: str) -> list[dict]:
    findings = []
    counts = [cell["execution_count"] for cell in notebook.cells if cell["execution_count"] is not None]
    if counts and counts != sorted(counts):
        findings.append(_shape("nb-out-of-order", path, 1, f"Execution counts run {counts[:8]}.", {}, ""))
    defined: set[str] = set()
    later: dict[str, int] = {}
    per_cell = []
    for cell in notebook.cells:
        loads, stores = _cell_names(cell["source"])
        per_cell.append((cell["number"], loads, stores))
        for name in stores:
            later.setdefault(name, cell["number"])
    import builtins
    known = set(dir(builtins)) | {"get_ipython", "display", "In", "Out", "_", "__"}
    for number, loads, stores in per_cell:
        for name, line in loads.items():
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


def _cell_names(cell_source: str) -> tuple[dict, set]:
    import ast
    cleaned = "\n".join(re.sub(r"^(\s*)[%!].*", r"\1pass", line) for line in cell_source.split("\n"))
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return {}, set()
    loads: dict[str, int] = {}
    stores: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                stores.add(node.id)
            else:
                loads.setdefault(node.id, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stores.add(node.name)
            if not isinstance(node, ast.ClassDef):
                stores.update(a.arg for a in node.args.args + node.args.kwonlyargs)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            stores.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            stores.add(node.name)
        elif isinstance(node, ast.Lambda):
            stores.update(a.arg for a in node.args.args)
    return loads, stores


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
        except sqlite3.Error:
            self.connection = None

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


def _analyze_in_workers(pending: list[tuple[str, str]], count: int) -> list[dict]:
    """Spawned workers put the working directory on sys.path, so a repository's multiprocessing.py would run. Start them somewhere empty."""
    home = os.getcwd()
    try:
        with tempfile.TemporaryDirectory(prefix="occam-") as empty:
            os.chdir(empty)
            try:
                with ProcessPoolExecutor(max_workers=count) as pool:
                    return list(pool.map(_analyze_for_pool, pending, chunksize=32))
            finally:
                os.chdir(home)
    except (OSError, RuntimeError):
        return [_analyze_for_pool(item) for item in pending]


# ---------------------------------------------------------------- scan


class ScanResult:
    def __init__(self, findings: list[dict], stats: dict, project: Project | None) -> None:
        self.findings = findings
        self.stats = stats
        self.project = project


def run_scan(root: Path, targets: list[str] | None = None, changed_only: bool = False, base: str | None = None, use_cache: bool = True,
             workers: int | None = None, project_rules: bool = True, isolated: bool = False) -> ScanResult:
    """Scan the repository, or just what changed against base.

    Project-wide facts come from the whole repository, so a changed-only scan still knows about the code around it. That costs about 0.55 GB per million
    lines however little was asked for, so isolated reads only what was selected and leaves out the rules that need the rest.
    """
    started = time.time()
    config = filesystem.load_config(root)
    selected = filesystem.list_files(root, targets, config) if targets else filesystem.list_files(root, None, config)
    all_files = filesystem.list_files(root, None, config) if targets else selected
    project_rules = project_rules and not isolated
    changed = filesystem.changed_lines(root, base) if (changed_only or base) else None
    if changed is not None:
        wanted = set(changed)
        selected = [path for path in selected if path in wanted]
    elif changed_only or base:
        raise filesystem.BadRevision("Not a git repository, so there's no diff to scan.")
    all_files = selected if isolated else all_files
    state = None
    if use_cache:
        try:
            state = filesystem.state_dir(root)
        except OSError:
            state = None
    cache = Cache(state)
    records = _analyze_all(root, list(dict.fromkeys([*all_files, *selected])), cache, workers)
    cache.close()
    project = Project(root, list(records))
    for record in records.values():
        project.add_file(record["path"], record)
    findings: list[dict] = []
    parse_errors = []
    selected_set = set(selected)
    for path, record in records.items():
        if record.get("parse_error"):
            parse_errors.append((path, record["parse_error"]))
        if path in selected_set:
            findings += record["findings"]
    for finding in project.run(enabled=project_rules):
        if finding["path"] in selected_set:
            finding.setdefault("evidence", "")
            findings.append(finding)
    findings = project.refine(findings)
    findings = _apply_filters(findings, config, None)
    _decorate(findings)
    if changed is not None:
        findings = new_against_base(root, findings, base, _renames(root, base))
    languages = Counter(record["language"] for record in records.values() if record["language"] and record["path"] in selected_set)
    unscanned = sorted(path for path in selected if records[path].get("unscanned"))
    stats = {"isolated": isolated, "unscanned": unscanned, "generated": sorted(r["path"] for r in records.values() if r.get("generated") and r["path"] in selected_set),
             "suppressed_inline": sum(records[path].get("suppressed", 0) for path in selected),
             "config_ignored": config.get("ignore", []), "config_disabled": config.get("disable", []),
             "files": len(selected), "analyzed": sum(1 for r in records.values() if r["language"] and r["path"] in selected_set),
             "lines": sum(r["lines"] for r in records.values() if r["language"] and r["path"] in selected_set),
             "languages": dict(languages), "seconds": round(time.time() - started, 2), "parse_errors": parse_errors,
             "generated_skipped": sum(1 for r in records.values() if r.get("generated")), "root": str(root),
             "not_parsed_languages": sorted(language for language in languages if language not in _PARSER_LANGUAGES)}
    return ScanResult(findings, stats, project)


def _analyze_all(root: Path, paths: list[str], cache: Cache, workers: int | None, light: bool = False) -> dict[str, dict]:
    records: dict[str, dict] = {}
    pending: list[tuple[str, str]] = []
    keys: dict[str, str] = {}
    texts: dict[str, str] = {}
    for path in paths:
        language = src.language_of(path)
        if language is None:
            head = _head(root / path)
            language = src.language_of(path, head)
        if language is None:
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
    computed: list[dict] = []
    count = workers if workers is not None else (os.cpu_count() or 2)
    if len(pending) >= _PARALLEL_FROM and count > 1:
        computed = _analyze_in_workers(pending, count)
    else:
        computed = [_analyze_for_pool(item) for item in pending]
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


def _apply_filters(findings: list[dict], config: dict, changed: dict[str, set[int]] | None) -> list[dict]:
    disabled = set(config.get("disable", []))
    return [finding for finding in findings if finding["rule"] not in disabled]


def _renames(root: Path, base: str | None) -> dict[str, str]:
    return filesystem.removed_and_renamed(root, base)[1]


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


def filter_findings(findings: list[dict], min_confidence: str = "medium", min_severity: str = "low", categories: list[str] | None = None,
                    rules: list[str] | None = None) -> list[dict]:
    confidence_cut = CONFIDENCES.index(min_confidence)
    severity_cut = SEVERITIES.index(min_severity)
    return [f for f in findings if CONFIDENCES.index(f["confidence"]) <= confidence_cut and SEVERITIES.index(f["severity"]) <= severity_cut
            and (not categories or f["category"] in categories) and (not rules or f["rule"] in rules)]


def scan_text(path: str, text: str, language: str | None = None) -> list[dict]:
    """Scan one piece of code with no repository around it: a snippet, a cell, a hook's view of one file."""
    record = analyze_text(path, text, language)
    findings = _apply_filters(record["findings"], {}, None)
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
    findings = _apply_filters(findings, {}, None)
    _decorate(findings)
    stats = {"files": 1, "analyzed": 1, "lines": record["lines"], "languages": {record["language"] or "unknown": 1}, "seconds": 0.0,
             "parse_errors": [(path, record["parse_error"])] if record.get("parse_error") else [], "generated_skipped": 0, "root": "(snippet)",
             "not_parsed_languages": []}
    return ScanResult(findings, stats, project)

