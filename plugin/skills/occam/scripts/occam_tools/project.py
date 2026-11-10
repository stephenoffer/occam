"""Rules that need more than one file: imports, dead code, duplication, class families, tests, repository shape."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

from functools import partial

from . import clones, imports, manifests
from .source import is_script_path, is_test_path

Finding = dict
_ENTRY_FILES = re.compile(r"(^|/)(__main__|__init__|conftest|setup|manage|wsgi|asgi|main|app|cli|run|server|index|noxfile|fabfile|tasks|gunicorn\.conf|conf)\.py$")
_COMMON_NAMES = {"main", "run", "setup", "teardown", "get", "set", "init", "start", "stop", "close", "open", "read", "write", "load", "save", "update",
                 "create", "delete", "execute", "process", "handle", "parse", "to_dict", "from_dict", "to_json", "from_json", "validate", "render", "build",
                 "configure", "register", "connect", "reset", "clear", "add", "remove", "index", "default", "wrapper", "decorator", "inner", "helper", "callback"}
_VERB_FAMILIES = [
    {"get", "fetch", "retrieve", "load", "read", "find", "lookup", "query"},
    {"create", "make", "build", "generate", "construct"},
    {"delete", "remove", "destroy", "drop", "purge"},
    {"update", "modify", "change", "patch", "edit"},
    {"validate", "verify", "check", "ensure"},
    {"parse", "decode", "deserialize"},
    {"format", "render", "serialize", "encode"},
    {"compute", "calculate", "calc"},
    {"send", "dispatch", "emit", "publish"},
]
_SCRATCH_FILE = re.compile(
    r"(?:^|[/_.-])(?:old|new|bak|backup|orig|copy|fixed|final|temp|tmp|scratch|wip|v\d+)(?:\.\w+$|\s*\(\d+\)\.\w+$)"
    r"|(?:^|/)(?:copy of |temp_|tmp_|debug_|scratch|test_fix|fix_|quick_test|try_|experiment_|untitled)[^/]*$|\.(?:bak|orig|rej|swp)$|~$", re.I)
_REPORT_FILE = re.compile(
    r"(?:^|/)(?:IMPLEMENTATION|COMPLETION|REFACTOR(?:ING)?|FIX(?:ES)?|CHANGES|UPDATE|PROGRESS|STATUS|SUMMARY|PHASE|MIGRATION_(?:SUMMARY|COMPLETE)|DONE|FINAL|WORK|TASK|AUDIT|REVIEW)"
    r"[_-]?(?:SUMMARY|REPORT|COMPLETE|STATUS|NOTES|PLAN|LOG|\d+)?[^/]*\.(?:md|txt)$", re.I)
_ARTIFACT = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|\.DS_Store|\.coverage|htmlcov|\.tox|\.idea|\.next)(/|$)|\.pyc$|\.class$|\.o$")
_SECRET_FILE = re.compile(r"(^|/)(\.env(\.[\w-]+)?|\.npmrc|\.pypirc|id_rsa|id_ed25519|credentials\.json|service[-_]account[^/]*\.json|[^/]+\.pem|[^/]+\.key|[^/]+\.p12|[^/]+\.pfx)$")
_NOT_SECRET_FILE = re.compile(r"\.(example|sample|template|dist|defaults?)$|example|sample", re.I)
_CONFIG_MODULE = re.compile(r"(?:^|/)(config|settings|conf|configuration)\.py$")
_UTILITY_FILE = re.compile(r"(?:^|/)(utils?|helpers?|common|misc|shared)\.(?:py|js|ts|go|java|kt)$")
_CONSEQUENCE = re.compile(r"(?:^|[/_.\-])(?:auth(?!ors?(?:[/_.\-]|$))\w*|login|tokens?|passwords?|secrets?|credentials?|permissions?|acl|rbac|tenan\w+|billing|payments?|invoices?|checkout|refunds?|ledgers?|migrat\w*|crypto\w*|webhooks?|signatures?|admin|sessions?)(?:[/_.\-]|$)", re.I)
_LARGE_BINARY = 5_000_000
_HIDES_CHECKS = re.compile(r"addopts.*(?:--ignore|--deselect|-k\s*[\"']?not\b)|^\s*(?:continue-on-error\s*:\s*true|ignore_errors\s*=\s*[Tt]rue|testPathIgnorePatterns)|^\s*(?:--ignore|--deselect)\b|^\s*collect_ignore(?:_glob)?\s*(?::[^=\n]+)?(?:\+?=|\.(?:append|extend)\b)")
_SOURCE_LANGUAGES = {"python", "javascript", "typescript", "go", "rust", "java", "kotlin", "c", "cpp", "csharp", "swift", "ruby", "php", "scala"}


def _finding(rule: str, path: str, line: int, message: str, **extra) -> Finding:
    return {"rule": rule, "path": path, "line": line, "message": message, **extra}


def _index_definition(path: str, definition: dict, by_hash: dict, by_name: dict, by_action: dict) -> None:
    """Where one definition belongs for each kind of repetition: same structure, same name, or same action."""
    name = definition["name"]
    statements = definition.get("statements", 0)
    if definition.get("hash") and statements >= 4 and definition.get("length", 0) >= 6:
        by_hash[definition["hash"]].append((path, definition))
    elif definition.get("exact"):
        by_hash["exact:" + definition["exact"]].append((path, definition))  # short: the same code, not just the same shape, and three copies
    if definition["kind"] != "function" or definition.get("decorated"):
        return  # a route handler named after the service it calls isn't a second implementation
    bare = name.lstrip("_")
    if statements >= 4 and bare not in _COMMON_NAMES and ("_" in bare or re.search(r"[a-z][A-Z]", bare)) and not bare.startswith("test"):
        by_name[bare].append((path, definition))
    words = bare.split("_")
    if statements >= 3 and len(words) >= 2:
        for family, verbs in enumerate(_VERB_FAMILIES):
            if words[0] in verbs:
                by_action[(family, "_".join(words[1:]))].append((path, definition, words[0]))


class _CallSites(NamedTuple):
    shapes: dict        # called name -> how each file calls it
    value_uses: set     # names passed around instead of called
    def_counts: Counter
    class_counts: Counter
    unseen_classes: set  # with a base, a subclass or a decorator, so other code may call or override their methods


def _call_sites(all_facts) -> _CallSites:
    sites = _CallSites(defaultdict(list), set(), Counter(), Counter(), set())
    for facts in all_facts:
        for name, shape in (facts.get("calls") or {}).items():
            sites.shapes[name].append(shape)
        sites.value_uses.update(facts.get("value_uses") or [])
        sites.def_counts.update(definition["name"] for definition in facts.get("defs", []))
        for item in facts.get("classes", []):
            bases = set(item.get("bases") or [])
            sites.class_counts[item["name"]] += 1
            sites.unseen_classes.update(bases - {"object"})
            if bases - {"object"} or item.get("decorated"):
                sites.unseen_classes.add(item["name"])
    return sites


def _call_key(definition: dict, sites: _CallSites, facts: dict, library: bool) -> str | None:
    """The name callers use for this definition, if it can only mean this one and every caller is in this repository."""
    name, owner = definition["name"], definition.get("class")
    if _callers_may_be_unseen(definition, sites, facts, library):
        return None
    if name == "__init__":
        calls = facts.get("calls") or {}
        built_indirectly = "cls" in calls or "__class__" in calls  # `cls(...)` and `type(self)(...)` build this class under another name
        return owner if owner and sites.class_counts[owner] == 1 and not built_indirectly else None
    return None if name.startswith("__") or sites.def_counts[name] != 1 else name


def _callers_may_be_unseen(definition: dict, sites: _CallSites, facts: dict, library: bool) -> bool:
    name, owner = definition["name"], definition.get("class")
    public = owner or name
    exported = public in (facts.get("exports") or []) or (library and not public.startswith("_"))
    return bool(definition.get("decorated")) or owner in sites.unseen_classes or name in ("main", "cli") or exported


def _options_nobody_passes(options: list, key: str, sites: _CallSites) -> list[str]:
    found = sites.shapes.get(key, [])
    if not found or key in sites.value_uses or any(shape[3] for shape in found):
        return []
    most_positional = max(shape[1] for shape in found)
    passed = {keyword for shape in found for keyword in shape[2]}
    return [option for option, position in options if option not in passed and (position < 0 or position >= most_positional)]


def _module_names(path: str) -> list[str]:
    """Dotted names this Python file could be imported as, depending on the source root."""
    stem = path[:-3] if path.endswith(".py") else path
    parts = stem.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts))]


class Project:
    """Everything known about the repository after each file has been analyzed."""

    def __init__(self, root: Path | None, files: list[str]) -> None:
        self.root = root
        self.files = files
        self.facts: dict[str, dict] = {}
        self.languages: dict[str, str] = {}
        self.lines: dict[str, int] = {}
        self.identifier_counts: Counter = Counter()
        self.test_identifiers: set[str] = set()
        self.clone_index = clones.CloneIndex()
        self.findings: list[Finding] = []
        self.pulled_up: set[tuple[str, int]] = set()  # methods pull-up-method already reports, so clone-function doesn't say it again

    def add_file(self, path: str, record: dict) -> None:
        facts = record.get("facts") or {}
        self.facts[path] = facts
        self.languages[path] = record.get("language") or ""
        self.lines[path] = record.get("lines", 0)
        idents = record.get("identifiers") or {}
        self.identifier_counts.update(idents)
        if is_test_path(path):
            self.test_identifiers.update(idents)
        table = record.get("line_table")
        if table is not None:
            self.clone_index.add(path, table, record.get("fingerprints") or {"exact": [], "renamed": []})

    def run(self, enabled: bool = True, whole: bool = True) -> list[Finding]:
        """`whole` is False when some files weren't read. Only the first pass judges each file on its own, so only it can still run: a committed secret file stays reported."""
        passes = [self._repository_files, partial(imports.python_imports, self), partial(imports.foreign_imports, self), partial(imports.stdlib_attributes, self), partial(imports.local_attributes, self), self._dead_code, self._unused_options,
                  self._duplicates, self._class_families, self._twins, self._queries_through_helpers, self._import_graph, self._tests, self._dependency_use, self._config_modules, self._utility_buckets, self._settings, self._hidden_checks]
        for step in (passes if whole else passes[:1]) if enabled else []:
            step()
        return self.findings

    def add(self, *args, **kwargs) -> None:
        self.findings.append(_finding(*args, **kwargs))

    def refine(self, findings: list[Finding]) -> list[Finding]:
        """Per-file rules can't see the rest of the repository. Drop what the whole picture explains."""
        has_children: set[str] = set()
        reexports: set[tuple[str, str]] = set()
        modules, _ = self._local_modules()
        for path, facts in self.facts.items():
            for item in (facts or {}).get("classes", []):
                has_children.update(item.get("bases", []))
            for item in (facts or {}).get("imports", []):
                dotted = self._resolve_relative(path, item["module"], item["level"]) if item.get("level") else item["module"]
                target = modules.get(dotted) if dotted else None
                if target:
                    reexports.update((target, name) for name in item.get("names") or [])
        kept = []
        for finding in findings:
            if finding["rule"] in ("stub-raise", "stub-body", "lsp-violation") and finding.get("owner") in has_children:
                continue  # an intermediate class in a hierarchy: its subclasses supply the behavior
            if finding["rule"] == "unused-import" and (finding["path"], finding["message"].split(" ", 1)[0]) in reexports:
                continue  # another module imports this name from here, so it's being re-exported
            if finding["rule"] == "swallowed-exception" and not _CONSEQUENCE.search(finding["path"]):
                finding["severity"] = "medium"  # on real repositories most were best-effort cleanup. Where money or auth is handled, the rule's high stands
            kept.append(finding)
        return kept

    # ------------------------------------------------------------ repository shape

    def _repository_files(self) -> None:
        seen_artifacts: set[str] = set()
        for path in self.files:
            size_known = self.root is not None
            if _SECRET_FILE.search(path) and not _NOT_SECRET_FILE.search(path):
                self.add("committed-secret-file", path, 1, "This file usually holds secrets, and it's tracked or about to be.")
            artifact = _ARTIFACT.search(path)
            if artifact:
                folder = path[:artifact.end()] if artifact.group(2) else path
                if folder not in seen_artifacts:
                    seen_artifacts.add(folder)
                    self.add("committed-artifact", path, 1, f"{folder} is generated output and isn't ignored, so it will end up in version control.")
            if _REPORT_FILE.search(path):
                self.add("ai-report-file", path, 1, "This looks like a work report, not documentation.")
            if _SCRATCH_FILE.search(path) and not is_test_path(path.replace("test_fix", "x")) or re.search(r"(?:^|/)test_fix[^/]*$", path):
                self.add("scratch-file", path, 1, "The name suggests a leftover copy or experiment.")
            if size_known:
                try:
                    size = (self.root / path).stat().st_size
                except OSError:
                    continue
                if size > _LARGE_BINARY and self.languages.get(path) in (None, ""):
                    self.add("large-binary", path, 1, f"{size // 1_000_000} MB in version control.")
            if self.languages.get(path) == "python" and re.search(r"(?:^|/)test_[^/]+\.py$", path):
                facts = self.facts.get(path) or {}
                has_tests = any(d["name"].startswith("test") for d in facts.get("defs", []))
                if facts and not has_tests and not any(c["name"].startswith("Test") for c in facts.get("classes", [])) and facts.get("has_main_guard"):
                    self.add("scratch-file", path, 1, "Named like a test, but it's a script pytest won't run.")

    # ------------------------------------------------------------ imports

    def _manifests(self) -> dict:
        if not hasattr(self, "_manifest_cache"):
            self._manifest_cache = manifests.read_manifests(self.root, self.files) if self.root else {
                "python": {}, "python_locked": set(), "node": {}, "rust": {}, "go": {}, "go_own": set(), "aliases": set(), "files": []}
        return self._manifest_cache

    def _python_paths(self) -> list[str]:
        return [p for p, language in self.languages.items() if language in ("python", "notebook")]

    def _local_modules(self) -> tuple[dict[str, str], set[str]]:
        if hasattr(self, "_local_cache"):
            return self._local_cache
        modules: dict[str, str] = {}
        tops: set[str] = set()
        for path in self.files:
            parts = path.split("/")
            for part in parts[:-1]:
                tops.add(part)
            if path.endswith((".py", ".pyi", ".so", ".pyd")):
                tops.add(parts[-1].split(".")[0])
            if path.endswith(".py"):
                for name in _module_names(path):
                    modules.setdefault(name, path)
        self._local_cache = (modules, tops)
        return self._local_cache

    def _canonical_modules(self) -> dict[str, list[str]]:
        """Each module under the name it is imported by: from the first folder up that isn't a package."""
        if not hasattr(self, "_canonical_cache"):
            present = self._present = set(self.files)
            names: dict[str, list[str]] = defaultdict(list)
            for path in self.files:
                if not path.endswith(".py"):
                    continue
                parts = path[:-3].split("/")
                if parts[-1] == "__init__":
                    parts.pop()
                start = len(parts) - 1
                while start > 0 and "/".join(parts[:start]) + "/__init__.py" in present:
                    start -= 1
                if parts:
                    names[".".join(parts[start:])].append(path)
            self._canonical_cache = names
        return self._canonical_cache

    def python_target(self, importer: str, dotted: str) -> str | None:
        """The file an absolute import names, or None if that can't be told. Matching any path suffix would read `import json` as a project's own foundation/json.py."""
        present = self._canonical_modules() and self._present
        relative = dotted.replace(".", "/")
        folder = importer.rsplit("/", 1)[0] + "/" if "/" in importer else ""
        bases = ("",) if not folder or folder + "__init__.py" in present else (folder, "")  # a script's own folder is on its path, and a package's isn't
        for base in bases:
            for candidate in (f"{base}{relative}.py", f"{base}{relative}/__init__.py"):
                if candidate in present:
                    return candidate
        named = self._canonical_modules().get(dotted, [])
        return named[0] if len(named) == 1 else None

    def _resolve_relative(self, path: str, module: str, level: int) -> str | None:
        parts = path.split("/")[:-1]
        if level > 1:
            if level - 1 > len(parts):
                return None
            parts = parts[:-(level - 1)]
        return ".".join(parts + ([module] if module else []))

    # ------------------------------------------------------------ dead code

    def _is_library(self) -> bool:
        if not self.root:
            return False
        for name in ("pyproject.toml", "setup.py", "setup.cfg"):
            path = self.root / name
            if path.exists():
                try:
                    if re.search(r"^\[project\]|^name\s*=|setup\(", path.read_text(errors="replace"), re.M):
                        return True
                except OSError:
                    pass
        return False

    def _build_imported_by(self) -> dict[str, set[str]]:
        imported_by: dict[str, set[str]] = defaultdict(set)
        modules, _ = self._local_modules()
        for path in self._python_paths():
            for item in (self.facts.get(path) or {}).get("imports", []):
                dotted = self._resolve_relative(path, item["module"], item["level"]) if item.get("level") else item["module"]
                if dotted is None:
                    continue
                for candidate in [dotted, *(f"{dotted}.{name}" for name in item.get("names") or [])]:
                    target = modules.get(candidate)
                    if target and target != path:
                        imported_by[target].add(path)
        return imported_by

    def _dead_code(self) -> None:
        library = self._is_library()
        self._imported_by = self._build_imported_by()
        for path in self._python_paths():
            facts = self.facts.get(path) or {}
            if facts and not is_test_path(path):
                self._unreferenced(path, facts, library)
                self._orphan(path, facts)

    def _unreferenced(self, path: str, facts: dict, library: bool) -> None:
        counts = self.identifier_counts
        exports = set(facts.get("exports") or [])
        for definition in facts.get("defs", []):
            name = definition["name"]
            skip = definition["kind"] != "function" or definition.get("decorated") or name in exports or name.startswith("__") or name in ("main", "cli") or len(name) < 3  # identifiers() doesn't count names this short
            if not skip and counts.get(name, 0) <= 1:
                confident = name.startswith("_") or not library
                self.add("unreferenced-def", path, definition["line"], f"{name} has no references in this repository.", confidence="medium" if confident else "low")
        for item in facts.get("classes", []):
            if item["name"] not in exports and counts.get(item["name"], 0) <= 1 and not item["name"].startswith("Test") and len(item["name"]) >= 3:
                self.add("unreferenced-def", path, item["line"], f"Class {item['name']} has no references in this repository.", confidence="medium" if not library else "low")

    def _unused_options(self) -> None:
        """Options no caller passes, only where every call can be seen. Decorated or overridden functions, ambiguous names, and names passed around or called with * or ** are left alone."""
        python = [*self._python_paths(), *(path for path in self.files if path.endswith((".py", ".pyi", ".pyx")))]  # too large to read, or Cython: Python by name, with no facts
        facts_by_path = {path: self.facts.get(path) or {} for path in python}
        if any("calls" not in facts or facts.get("dynamic_lookup") for facts in facts_by_path.values()):
            return  # a file that couldn't be read, or a computed lookup, may hold the call that passes it
        library = self._is_library()
        sites = _call_sites(self.facts.values())
        for path, facts in facts_by_path.items():
            for definition in () if is_test_path(path) else facts.get("defs", []):
                key = _call_key(definition, sites, facts, library) if definition.get("options") else None
                unused = _options_nobody_passes(definition["options"], key, sites) if key else []
                if unused:
                    shown = ", ".join(unused[:4]) + (f" and {len(unused) - 4} more" if len(unused) > 4 else "")
                    self.add("unused-option", path, definition["line"], f"No call read here passes {shown} to {key}().")

    def _orphan(self, path: str, facts: dict) -> None:
        if self._imported_by.get(path) or _ENTRY_FILES.search(path) or is_script_path(path) or facts.get("has_main_guard") or self.languages.get(path) != "python":
            return
        stem = path.rsplit("/", 1)[-1][:-3]
        own_defs = sum(1 for d in facts.get("defs", []) if d["name"] == stem)
        if self.identifier_counts.get(stem, 0) <= own_defs and self.lines.get(path, 0) >= 5:
            self.add("orphan-module", path, 1, f"Nothing imports or names {stem}.")

    # ------------------------------------------------------------ duplication

    def _duplicates(self) -> None:
        index = self.clone_index
        exact = index.clusters(1, clones.EXACT_WINDOW + clones.WINNOW - 1)
        for cluster in exact[:300]:
            members = cluster["members"]
            first = members[0]
            where = ", ".join(f"{p}:{a}-{b}" for p, a, b in members[1:5])
            extra = f" and {len(members) - 5} more" if len(members) > 5 else ""
            overrides = {"severity": "high"} if len(members) >= 4 or cluster["length"] >= 40 else {}
            if all(is_test_path(member[0]) for member in members):  # repeated setup in tests is normal, and rarely what to fix first
                overrides = {"confidence": "low"}
            self.add("clone-block", first[0], first[1], f"{cluster['length']} lines repeated at {where}{extra}.", related=[f"{p}:{a}" for p, a, _ in members[1:]], **overrides)
        exact_spots = {(c["members"][0][0], c["members"][0][1]) for c in exact}
        for cluster in index.clusters(2, clones.RENAMED_WINDOW + clones.WINNOW - 1)[:100]:
            members = cluster["members"]
            first = members[0]
            if (first[0], first[1]) not in exact_spots:
                where = ", ".join(f"{p}:{a}-{b}" for p, a, b in members[1:5])
                self.add("clone-renamed", first[0], first[1], f"{cluster['length']} lines repeated with renamed identifiers at {where}.", related=[f"{p}:{a}" for p, a, _ in members[1:]])

    def _queries_through_helpers(self) -> None:
        """N+1 through a helper: a loop calling this repository's own function that queries or calls out itself, which a rule reading one file can't see.
        The name has to be defined once, here or in what this file imports by name, and a decorated helper may cache, so it's left alone."""
        definitions: dict[str, list] = defaultdict(list)
        for path, facts in self.facts.items():
            for definition in (facts or {}).get("defs", []):
                if definition["kind"] == "function":
                    definitions[definition["name"]].append((path, definition))
        for path, facts in self.facts.items():
            if not facts or is_test_path(path) or not facts.get("loop_calls"):
                continue
            imported = {name for item in facts.get("imports", []) for name in item.get("names", [])}
            for name, line in facts["loop_calls"]:
                found = definitions.get(name, [])
                if len(found) != 1:
                    continue
                where, definition = found[0]
                if definition.get("remote") and not definition.get("decorated") and (where == path or name in imported):
                    self.add("query-in-loop", path, line, f"{name}() queries or calls out ({where}:{definition['line']}), and this runs it once per item.", related=[f"{where}:{definition['line']}"])

    def _twins(self) -> None:
        by_hash: dict[str, list] = defaultdict(list)
        by_name: dict[str, list] = defaultdict(list)
        by_action: dict[tuple[int, str], list] = defaultdict(list)
        for path, facts in self.facts.items():
            if is_test_path(path) or not facts:
                continue
            for definition in facts.get("defs", []):
                if not definition["name"].startswith("__"):
                    _index_definition(path, definition, by_hash, by_name, by_action)
        self._same_shape(by_hash)
        self._same_name(by_name)
        self._same_action(by_action)

    def _same_shape(self, by_hash: dict[str, list]) -> None:
        for key, group in by_hash.items():
            short = key.startswith("exact:")
            if len(group) >= (3 if short else 2) and not all((p, d["line"]) in self.pulled_up for p, d in group):
                path, definition = group[0]
                others = ", ".join(f"{p}:{d['line']} ({d['name']})" for p, d in group[1:5]) + (f" and {len(group) - 5} more" if len(group) > 5 else "")
                what = "is the same code as" if short else "has the same structure as"
                self.add("clone-function", path, definition["line"], f"{definition['name']} {what} {others}.", related=[f"{p}:{d['line']}" for p, d in group[1:]])

    def _same_name(self, by_name: dict[str, list]) -> None:
        for name, group in by_name.items():
            hashes = {d.get("hash") for _, d in group}
            if len({path for path, _ in group}) >= 2 and (len(hashes) >= 2 or None in hashes):
                path, definition = group[0]
                others = ", ".join(f"{p}:{d['line']}" for p, d in group[1:5])
                self.add("diverged-twin", path, definition["line"], f"{name} is also defined differently at {others}. Check which behavior is right.", related=[f"{p}:{d['line']}" for p, d in group[1:]])

    def _same_action(self, by_action: dict[tuple[int, str], list]) -> None:
        for (_, noun), group in by_action.items():
            verbs = {verb for _, _, verb in group}
            paths = {path for path, _, _ in group}
            if len(verbs) >= 2 and len(paths) >= 2 and len(noun) >= 3:
                path, definition, _ = group[0]
                names = sorted({d["name"] for _, d, _ in group})
                self.add("parallel-verbs", path, definition["line"], f"{', '.join(names[:5])} look like the same operation in different files.", related=[f"{p}:{d['line']}" for p, d, _ in group[1:]])

    # ------------------------------------------------------------ class families

    def _class_families(self) -> None:
        classes: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        children: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        for path, facts in self.facts.items():
            for item in (facts or {}).get("classes", []):
                classes[item["name"]].append((path, item))
                for base in item.get("bases", []):
                    children[base].append((path, item))
        self._abstractions(classes, children)
        self._pull_up(classes)
        self._bypassed_bases(classes, children)
        self._inheritance_depth(classes)

    def _abstractions(self, classes, children) -> None:
        for name, group in classes.items():
            path, item = group[0]
            if not item.get("abstract") or is_test_path(path):
                continue
            implementations = [c for c in children.get(name, []) if not is_test_path(c[0])]
            if len(implementations) <= 1 and not name.endswith(("Error", "Exception")):
                count = len(implementations)
                self.add("single-impl-abstraction", path, item["line"], f"{name} has {'one implementation' if count == 1 else 'no implementations'} in this repository.",
                         **({"confidence": "low"} if self._is_library() else {}))

    def _pull_up(self, classes) -> None:
        seen = set()
        method_owners: dict[tuple[str, str], list] = defaultdict(list)
        for name, group in classes.items():
            for path, item in group:
                if is_test_path(path):
                    continue
                for method, facts in (item.get("methods") or {}).items():
                    if facts.get("statements", 0) >= 3 and not method.startswith("__"):
                        method_owners[(method, facts["hash"])].append((path, name, facts["line"]))
        for (method, _), owners in method_owners.items():
            names = sorted({owner[1] for owner in owners})
            if len(names) >= 2 and tuple(names) not in seen:
                seen.add(tuple(names))
                self.pulled_up.update((p, line) for p, _, line in owners)
                path, _, line = owners[0]
                self.add("pull-up-method", path, line, f"{method} is identical in {', '.join(names[:5])}.", related=[f"{p}:{line}" for p, _, line in owners[1:]])

    def _bypassed_bases(self, classes, children) -> None:
        for base, group in classes.items():
            match = re.match(r"^(?:Base|Abstract)([A-Z]\w+)$|^(\w+?)(?:Base)$", base)
            suffix = (match.group(1) or match.group(2)) if match else None
            if not suffix or len(children.get(base, [])) < 2:
                continue
            base_methods = {m for _, item in group for m in (item.get("methods") or {}) if not m.startswith("__")}
            if len(base_methods) < 2:
                continue
            for name, members in classes.items():
                if name == base or not name.endswith(suffix) or name == suffix or name.endswith(("Error", "Exception", "Warning")):
                    continue
                for path, item in members:
                    shared = base_methods & set(item.get("methods") or {})
                    if base not in item.get("bases", []) and not is_test_path(path) and not any(b.endswith(suffix) for b in item.get("bases", [])) \
                            and len(shared) >= max(2, len(base_methods) // 2):
                        self.add("base-class-bypassed", path, item["line"], f"{name} doesn't extend {base}, though {len(children[base])} similar classes do, and it repeats {', '.join(sorted(shared)[:4])}.")

    def _inheritance_depth(self, classes) -> None:
        parents = {name: group[0][1].get("bases", []) for name, group in classes.items()}

        def depth(name: str, trail: tuple = ()) -> int:
            if name in trail or name not in parents:
                return 0
            return 1 + max((depth(base, (*trail, name)) for base in parents[name]), default=0)

        for name, group in classes.items():
            found = depth(name)
            if found >= 5 and not is_test_path(group[0][0]) and not name.endswith(("Error", "Exception", "Warning")):
                self.add("deep-inheritance", group[0][0], group[0][1]["line"], f"{name} is {found} levels deep.")

    # ------------------------------------------------------------ module graph

    def _build_graph(self, include_optional: bool = False) -> dict[str, set[str]]:
        """Import edges. Optional and function-level imports don't count as a design dependency, but a change does reach them, so `query` asks for them."""
        graph: dict[str, set[str]] = defaultdict(set)
        modules, _ = self._local_modules()
        for path in self._python_paths():
            for item in (self.facts.get(path) or {}).get("imports", []):
                reached_anyway = include_optional and (item.get("optional") or item.get("lazy"))
                if not reached_anyway and (item.get("optional") or not item.get("runtime", True)):
                    continue
                dotted = self._resolve_relative(path, item["module"], item["level"]) if item.get("level") else item["module"]
                if dotted:
                    candidates = [dotted, *(f"{dotted}.{name}" for name in item.get("names") or [])]
                    graph[path].update(modules[c] for c in candidates if modules.get(c) and modules[c] != path)
        for path, language in self.languages.items():
            if language in ("javascript", "typescript"):
                for item in (self.facts.get(path) or {}).get("imports", []):
                    target = self._resolve_js(path, item["module"]) if item["module"].startswith(".") else None
                    if target and target != path:
                        graph[path].add(target)
        return graph

    def _import_graph(self) -> None:
        graph = self._build_graph()
        self.graph = graph
        for component in strongly_connected(graph):
            if len(component) >= 2:
                members = sorted(component)
                via_init = any(member.endswith("__init__.py") for member in members)
                overrides = {"confidence": "low"} if via_init and len(members) == 2 else {"confidence": "medium"} if via_init else {}
                self.add("import-cycle", members[0], 1, f"{len(members)} modules import each other: {', '.join(members[:6])}" + ("..." if len(members) > 6 else ""), related=members[1:], **overrides)
        fan_in: Counter = Counter()
        for targets in graph.values():
            fan_in.update(targets)
        if len(graph) >= 30:
            for path, targets in graph.items():
                if len(targets) >= 15 and fan_in[path] >= 15:
                    self.add("hub-module", path, 1, f"Imports {len(targets)} modules and is imported by {fan_in[path]}.")

    def _resolve_js(self, path: str, module: str) -> str | None:
        parts: list[str] = []
        for part in (str(Path(path).parent) + "/" + module).split("/"):
            if part == ".." and parts:
                parts.pop()
            elif part not in (".", ""):
                parts.append(part)
        target = "/".join(parts)
        stripped = re.sub(r"\.(js|jsx|mjs|cjs)$", "", target)
        if not hasattr(self, "_file_set"):  # building it costs a millisecond at 50,000 files, and this runs once per import
            self._file_set = set(self.files)
        files = self._file_set
        for option in (target, *(f"{stripped}{e}" for e in imports.JS_EXTENSIONS), *(f"{target}/index{e}" for e in imports.JS_EXTENSIONS)):
            if option in files:
                return option
        return None

    # ------------------------------------------------------------ tests

    def _source_files(self) -> list[str]:
        return [p for p, language in self.languages.items() if language in _SOURCE_LANGUAGES and not is_test_path(p) and not is_script_path(p)]

    def untested_modules(self) -> list[tuple[str, int, bool]]:
        """(path, lines, high consequence) for source no test imports or names, consequence and size first."""
        imported_by = getattr(self, "_imported_by", {})
        untested = []
        for path in self._source_files():
            stem = path.rsplit("/", 1)[-1].split(".")[0]
            if self.lines.get(path, 0) < 15 or stem in ("__init__", "__main__", "index", "main", "conftest", "setup", "types", "constants", "config", "settings"):
                continue
            if any(is_test_path(importer) for importer in imported_by.get(path, ())) or stem in self.test_identifiers:
                continue
            defs = (self.facts.get(path) or {}).get("defs", [])
            if defs and any(d["name"] in self.test_identifiers for d in defs):
                continue
            consequence = bool(_CONSEQUENCE.search(path))
            untested.append((not consequence, -self.lines.get(path, 0), path, consequence))
        return [(path, -lines, consequence) for _, lines, path, consequence in sorted(untested)]

    def _tests(self) -> None:
        sources = self._source_files()
        tests = [p for p, language in self.languages.items() if language in _SOURCE_LANGUAGES and is_test_path(p)]
        total = sum(self.lines.get(p, 0) for p in sources)
        if not sources or total < 50:
            return
        if not tests:
            self.add("no-tests", sources[0], 1, f"{len(sources)} source files and {total} lines, and no test files.")
            return
        for path, _, consequence in self.untested_modules()[:40]:
            self.add("module-untested", path, 1, f"No test refers to this module ({self.lines.get(path, 0)} lines)." + (" It handles something high consequence." if consequence else ""),
                     **({"severity": "high"} if consequence else {}))

    # ------------------------------------------------------------ dependencies

    def _dependency_use(self) -> None:
        manifest = self._manifests()
        declared = manifest["python"]
        imported: set[str] = set()
        for path in self._python_paths():
            for item in (self.facts.get(path) or {}).get("imports", []):
                if not item.get("level"):
                    top = item["module"].split(".")[0]
                    imported.add(manifests.normalize_dist(manifests.IMPORT_TO_DIST.get(top, top)))
                    imported.add(manifests.normalize_dist(top))
        python_files = [p for p in self.files if p.endswith(".py")]
        if declared and python_files:
            tooling = re.compile(r"^(?:pytest|ruff|black|isort|mypy|pyright|flake8|pylint|coverage|tox|nox|pre-commit|sphinx|mkdocs|setuptools|wheel|hatchling|hatch|poetry|build|twine|pip|uv|types-|gunicorn|uvicorn|alembic|ipython|jupyter|bandit|semgrep|hypothesis)")
            frozen = {where for where in set(declared.values()) if manifests.looks_frozen(self.root, where)}
            for name, where in sorted(declared.items()):
                if tooling.match(name) or name in imported or any(i.startswith(name + "-") or name.startswith(i + "-") for i in imported):
                    continue
                if self.identifier_counts.get(name.replace("-", "_"), 0) > 0 or where in frozen:
                    continue
                self.add("unused-dependency", where, self._manifest_line(where, name), f"'{name}' is declared and never imported.")
        all_names = {manifests.normalize_dist(n) for n in declared} | set(manifest["node"]) | set(manifest["rust"])
        for label, family in manifests.COMPETING:
            present = sorted(all_names & family)
            if len(present) >= 2:
                where = (declared.get(present[0]) or manifest["node"].get(present[0]) or manifest["rust"].get(present[0]) or (manifest["files"] or [self.files[0] if self.files else ""])[0])
                self.add("competing-dependencies", where, 1, f"{label}: {', '.join(present)}.")

    def _manifest_line(self, where: str, name: str) -> int:
        try:
            for number, line in enumerate((self.root / where).read_text(errors="replace").split("\n"), start=1):
                if name in manifests.normalize_dist(line):
                    return number
        except OSError:
            pass
        return 1

    def _settings(self) -> None:
        for path, facts in self.facts.items():
            for name, own in ((facts or {}).get("settings") or {}).items():
                if self.identifier_counts.get(name, 0) <= own and len(name) >= 3:
                    self.add("unreferenced-setting", path, 1, f"Nothing outside this file reads {name}.")

    def _hidden_checks(self) -> None:
        for path in self.files:
            base = path.rsplit("/", 1)[-1]
            if base in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "conftest.py", "jest.config.js", "jest.config.ts", "vitest.config.ts") and self.root:
                try:
                    lines = (self.root / path).read_text(errors="replace").split("\n")
                except OSError:
                    continue
                for number, line in enumerate(lines, start=1):
                    if _HIDES_CHECKS.search(line):
                        self.add("checks-hidden-by-config", path, number, f"This config leaves checks out: {line.strip()[:90]}")

    def _config_modules(self) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for path in self.files:
            if _CONFIG_MODULE.search(path) and not is_test_path(path):
                groups[path.split("/")[0] if "/" in path else ""].append(path)
        for paths in groups.values():
            if len(paths) >= 2:
                self.add("duplicate-config", paths[0], 1, f"Configuration lives in {', '.join(paths[:5])}.", related=paths[1:])

    def _utility_buckets(self) -> None:
        for path in self.files:
            if _UTILITY_FILE.search(path) and self.lines.get(path, 0) >= 300:
                self.add("utility-bucket", path, 1, f"{self.lines[path]} lines in a catch-all module.")


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's algorithm, iterative so a deep graph can't hit the recursion limit."""
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    for start in list(graph):
        if start in indices:
            continue
        work = [(start, iter(graph.get(start, ())))]
        indices[start] = low[start] = index
        index += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, neighbors = work[-1]
            advanced = False
            for neighbor in neighbors:
                if neighbor not in indices:
                    indices[neighbor] = low[neighbor] = index
                    index += 1
                    stack.append(neighbor)
                    on_stack.add(neighbor)
                    work.append((neighbor, iter(graph.get(neighbor, ()))))
                    advanced = True
                    break
                if neighbor in on_stack:
                    low[node] = min(low[node], indices[neighbor])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == indices[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    return components
