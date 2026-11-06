"""Who depends on what: the import graph as something to ask, what a change reaches, and what tests reach.

Traces Python and JS or TS, including workspace packages and tsconfig paths, Go packages, Java and Kotlin imports, C and C++ local includes, Rust modules,
and sourced shell files. All of it reads text and syntax, so dynamic imports and plugin registration stay invisible, and the output says so.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import NamedTuple

from . import files as filesystem, rules_text
from .project import _CONSEQUENCE, Project, strongly_connected
from .query import Views, more, relative_path, safe_line, search, selected_files
from .scan import Cache, _analyze_all
from .source import is_script_path, is_test_path, language_of, load

MAX_SCRIPTS_SEARCHED = 2000
TRACED = {"python", "notebook", "javascript", "typescript", "go", "java", "kotlin", "c", "cpp", "rust", "shell"}
_GO_MODULE = re.compile(r"^module\s+(\S+)", re.M)
_GO_IMPORT = re.compile(r"""^[ \t]*(?:import[ \t]+)?(?:[\w.]+[ \t]+)?"([\w./\-]+)"[ \t]*(?://.*)?$""")
_JVM_IMPORT = re.compile(r"^[ \t]*import[ \t]+(?:static[ \t]+)?([\w.]*\w)(\.\*)?", re.M)
_JVM_PACKAGE = re.compile(r"^[ \t]*package[ \t]+([\w.]+)", re.M)
_C_INCLUDE = re.compile(r'''^[ \t]*#[ \t]*include[ \t]*(?:"([^"\n]+)"|<([^>\n]+/[^>\n]+)>)''', re.M)  # <a/b.h> can be local too, and <string.h> is left to the system
_RUST_MOD = re.compile(r"^[ \t]*(?:pub(?:\([^)\n]*\))?[ \t]+)?mod[ \t]+(\w+)[ \t]*;", re.M)
_RUST_USE = re.compile(r"^[ \t]*(?:pub(?:\([^)\n]*\))?[ \t]+)?use[ \t]+((?:crate|super|self|[a-zA-Z_]\w*)(?:::\w+)*)", re.M)
_PYTHON_IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+([^\n#]+)|import[ \t]+([^\n#]+))", re.M)
_INLINE_TESTS = r"#\[(cfg\(test\)|test)\]"
_SHELL_SOURCE = re.compile(r"""^[ \t]*(?:source|\.)[ \t]+["']?([^"'\s;&|]+)""", re.M)


class Graph(NamedTuple):
    edges: dict[str, set[str]]         # what a file imports, for questions about design: cycles and layers
    reverse: dict[str, set[str]]
    reach: dict[str, set[str]]         # also what running it runs without importing by name: parent packages, conftest.py, scripts a test names
    reach_reverse: dict[str, set[str]]
    project: Project
    untraced: Counter
    records: dict[str, dict]
    ambiguous: int                     # imports that could mean several files, all counted
    unread: list[str]                  # source that couldn't be read, so its imports are missing
    by_name: dict[str, set[str]]       # test to the scripts it reaches only by naming them
    inline_tests: set[str]             # source files carrying their own tests


def _load(root: Path) -> tuple[Project, dict[str, dict]]:
    """Facts for every file, from the scan's cache when it has them, without the parts of a record nothing here reads."""
    try:
        cache = Cache(filesystem.state_dir(root))
    except OSError:
        cache = Cache(None)
    records = _analyze_all(root, selected_files(root, None), cache, None, light=True)
    cache.close()
    project = Project(root, list(records))
    for record in records.values():
        project.add_file(record["path"], record)
    return project, records


def _normal(parts: list[str]) -> str:
    out: list[str] = []
    for part in parts:
        if part == "..":
            if out:
                out.pop()
        elif part not in (".", ""):
            out.append(part)
    return "/".join(out)


def _go_imports(text: str) -> list[str]:
    """Every import, in and out of blocks. By line, since a file can have several of each."""
    found = []
    in_block = False
    for line in text.split("\n"):
        stripped = line.strip()
        if in_block:
            in_block = stripped != ")"
        elif stripped.startswith("import") and stripped.rstrip().endswith("("):
            in_block = True
            continue
        elif not stripped.startswith("import"):
            continue
        match = _GO_IMPORT.match(line)
        if match:
            found.append(match.group(1))
    return found


def _go_edges(root: Path, files: list[str], add) -> None:
    modules = []
    for path in files:
        if path.rsplit("/", 1)[-1] == "go.mod":
            match = _GO_MODULE.search(filesystem.read_text(root / path) or "")
            if match:
                folder = path.rsplit("/", 1)[0] if "/" in path else ""
                modules.append((match.group(1), folder))
    by_folder: dict[str, list[str]] = defaultdict(list)
    go_files = [path for path in files if path.endswith(".go")]
    for path in go_files:
        by_folder[path.rsplit("/", 1)[0] if "/" in path else ""].append(path)
    for path in go_files:
        text = filesystem.read_text(root / path) or ""
        own = path.rsplit("/", 1)[0] if "/" in path else ""
        if path.endswith("_test.go"):
            for sibling in by_folder[own]:  # a test in the same package reaches its code with no import to read
                if sibling != path and not sibling.endswith("_test.go"):
                    add(path, sibling)
        for named in _go_imports(text):
            for module, folder in modules:
                if named == module or named.startswith(module + "/"):
                    inside = named[len(module):].lstrip("/")
                    target = "/".join(part for part in (folder, inside) if part)
                    for sibling in by_folder.get(target, []):
                        if not sibling.endswith("_test.go"):
                            add(path, sibling)


def _jvm_edges(root: Path, files: list[str], records: dict[str, dict], add) -> None:
    """Through each file's declared package, since Kotlin needn't keep folders in step with packages. Falls back to the path for a file with none."""
    jvm = [path for path in files if path.endswith((".java", ".kt", ".kts"))]
    texts = {path: filesystem.read_text(root / path) or "" for path in jvm}
    packages: dict[str, list[str]] = defaultdict(list)
    by_stem: dict[str, list[str]] = defaultdict(list)
    for path in jvm:
        match = _JVM_PACKAGE.search(texts[path])
        packages[match.group(1) if match else ""].append(path)
        by_stem[_stem(path)].append(path)
    for path in jvm:
        for match in _JVM_IMPORT.finditer(texts[path]):
            for target in _jvm_targets(match.group(1), bool(match.group(2)), packages, by_stem):
                add(path, target)
    for members in packages.values():  # same package needs no import, so the class name appearing is the only sign
        for path in members:
            words = records.get(path, {}).get("identifiers") or {}
            for other in members:
                if other != path and _stem(other) in words:
                    add(path, other)


def _stem(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _jvm_targets(dotted: str, wildcard: bool, packages: dict[str, list[str]], by_stem: dict[str, list[str]]) -> list[str]:
    if wildcard:
        return packages.get(dotted, [])
    package, _, name = dotted.rpartition(".")
    outer_package, _, outer = package.rpartition(".")  # a nested class or a static import names something inside the file
    for owner, stem in ((package, name), (outer_package, outer)):
        found = [path for path in packages.get(owner, []) if _stem(path) == stem]
        if found:
            return found
    tail = dotted.replace(".", "/")
    return [path for path in by_stem.get(name, []) if path.rsplit(".", 1)[0].endswith(tail)]


def _c_edges(root: Path, files: list[str], add) -> None:
    headers: dict[str, list[str]] = defaultdict(list)
    sources: dict[str, list[str]] = defaultdict(list)
    for path in files:
        if path.endswith((".h", ".hh", ".hpp", ".hxx")):
            headers[path.rsplit("/", 1)[-1]].append(path)
        elif path.endswith((".c", ".cc", ".cpp", ".cxx")):
            sources[path.rsplit("/", 1)[-1].rsplit(".", 1)[0]].append(path)
    for path in files:
        if not path.endswith((".h", ".hh", ".hpp", ".hxx", ".c", ".cc", ".cpp", ".cxx")):
            continue
        folder = path.split("/")[:-1]
        for match in _C_INCLUDE.finditer(filesystem.read_text(root / path) or ""):
            named = match.group(1) or match.group(2)
            direct = _normal([*folder, *named.split("/")])
            matches = [direct] if match.group(1) and (root / direct).is_file() else [c for c in headers.get(named.rsplit("/", 1)[-1], []) if c == named or c.endswith("/" + named)]
            for header in matches:
                add(path, header)
    for name, group in headers.items():  # including a header depends on what implements it
        stem = name.rsplit(".", 1)[0]
        for header in group:
            for source in sources.get(stem, []):
                add(header, source)


def _rust_edges(root: Path, files: list[str], add) -> None:
    rust = set(path for path in files if path.endswith(".rs"))
    crates: dict[str, str] = {}
    for path in files:
        if path.rsplit("/", 1)[-1] == "Cargo.toml":
            match = re.search(r'^[ \t]*name[ \t]*=[ \t]*"([^"\n]+)"', filesystem.read_text(root / path) or "", re.M)
            if match:
                crates[match.group(1).replace("-", "_")] = path.rsplit("/", 1)[0] if "/" in path else ""

    def module_file(parts: list[str]) -> str | None:
        joined = "/".join(parts)
        return next((c for c in (f"{joined}.rs", f"{joined}/mod.rs") if c in rust), None)

    for path in rust:
        text = filesystem.read_text(root / path) or ""
        folder = path.split("/")[:-1]
        stem = path.rsplit("/", 1)[-1][:-3]
        own = folder if stem in ("mod", "lib", "main") else [*folder, stem]
        for match in _RUST_MOD.finditer(text):
            target = module_file([*own, match.group(1)])
            if target:
                add(path, target)
        source_root = folder[:folder.index("src") + 1] if "src" in folder else folder
        for match in _RUST_USE.finditer(text):
            parts = match.group(1).split("::")
            if parts[0] == "crate":
                base, rest = source_root, parts[1:]
            elif parts[0] == "super":
                base, rest = own[:-1], parts[1:]
            elif parts[0] == "self":
                base, rest = own, parts[1:]
            elif parts[0] in crates:
                folder_of_crate = crates[parts[0]]
                base, rest = [*(folder_of_crate.split("/") if folder_of_crate else []), "src"], parts[1:]
                if not rest:
                    target = module_file([*base, "lib"])
                    if target:
                        add(path, target)
            else:
                continue
            for length in range(len(rest), 0, -1):  # `use a::b::Thing` names a file only as far as the modules go
                target = module_file([*base, *rest[:length]])
                if target:
                    add(path, target)
                    break


def _shell_edges(root: Path, files: list[str], languages: dict[str, str], add) -> None:
    names: dict[str, list[str]] = defaultdict(list)
    shell = [path for path in files if languages.get(path) == "shell"]
    for path in shell:
        names[path.rsplit("/", 1)[-1]].append(path)
    for path in shell:
        folder = path.split("/")[:-1]
        for match in _SHELL_SOURCE.finditer(filesystem.read_text(root / path) or ""):
            named = match.group(1)
            if "$" not in named:
                direct = _normal([*folder, *named.split("/")])
                if (root / direct).is_file():
                    add(path, direct)
                    continue
            for candidate in names.get(named.rsplit("/", 1)[-1], []):  # "$HERE/lib.sh" can't be resolved, and the file name usually can
                add(path, candidate)


def _mention_edges(root: Path, project: Project) -> dict[str, set[str]]:
    """A test that runs a script as a subprocess imports nothing, so naming its file is the only sign. Without this a CLI's own tests look unrelated to it.

    A comment doesn't run anything, and a path in the mention picks between same-named scripts. It's still only a name, so these are kept apart and labeled.
    """
    scripts: dict[str, list[str]] = defaultdict(list)
    for path, language in project.languages.items():
        name = path.rsplit("/", 1)[-1]
        if language and not is_test_path(path) and re.fullmatch(r"[\w.-]{4,}", name) and "." in name and (language == "shell" or is_script_path(path) or (project.facts.get(path) or {}).get("has_main_guard")):
            scripts[name].append(path)
    names = sorted(scripts)[:MAX_SCRIPTS_SEARCHED]
    found: dict[str, set[str]] = defaultdict(set)
    if not names:
        return found
    hits, _ = search(root, names, None, fixed=True, only=is_test_path)
    compiled = re.compile(r"(?<![\w.-])((?:\.{0,2}/)?(?:[\w.-]+/)*)(" + "|".join(re.escape(name) for name in names) + r")(?![\w-])")
    views = Views(root)
    for hit in hits:
        for match in compiled.finditer(hit.text):
            if views.kind_of(hit, match) == "comment":
                continue
            folder = re.sub(r"^(?:\.{0,2}/)+", "", match.group(1))
            found[hit.path].update(script for script in scripts[match.group(2)] if not folder or script.endswith(f"{folder}{match.group(2)}"))
    return found


def _python_edges(project: Project, add) -> int:
    """Python's own edges, resolved the way the importing file would resolve them. Returns how many could mean several files, which all count."""
    modules, _ = project._local_modules()
    canonical = project._canonical_modules()
    ambiguous = 0
    for path in project._python_paths():
        for item in (project.facts.get(path) or {}).get("imports", []):
            if not item.get("runtime", True) and not item.get("lazy"):
                continue  # only for type checkers
            relative = bool(item.get("level"))
            dotted = project._resolve_relative(path, item["module"], item["level"]) if relative else item["module"]
            for candidate in [dotted, *(f"{dotted}.{name}" for name in item.get("names") or [])] if dotted else []:
                target = modules.get(candidate) if relative else project.python_target(path, candidate)
                named = canonical.get(candidate, []) if target is None and not relative else []
                ambiguous += len(named) > 1
                for found in [target] if target else named:
                    add(path, found)
    return ambiguous


def _imports_by_pattern(project: Project, root: Path, records: dict[str, dict]) -> list[str]:
    """Files the scanner has no facts for still import things: a newer syntax than this Python, Python 2, or a comment that reads like a generated file's.

    Returns the source files that couldn't be read at all.
    """
    unread = []
    for path, record in records.items():
        if record.get("unscanned") and language_of(path) in TRACED:
            unread.append(path)
        language = record.get("language")
        if language not in ("python", "javascript", "typescript") or (project.facts.get(path) or {}).get("imports"):
            continue
        if not record.get("parse_error") and not record.get("generated"):
            continue
        text = filesystem.read_text(root / path) or ""
        project.facts[path] = {**(project.facts.get(path) or {}), "imports": _python_imports_in(text) if language == "python" else rules_text.import_facts(load(path, text, language))}
    return unread


def _python_imports_in(text: str) -> list[dict]:
    found = []
    for match in _PYTHON_IMPORT.finditer(text):
        if match.group(4):
            found += [{"module": part.split(" as ")[0].strip(), "names": [], "level": 0, "line": 1} for part in match.group(4).split(",")]
        else:
            names = [part.split(" as ")[0].strip(" ()") for part in match.group(3).split(",")]
            found.append({"module": match.group(2), "names": [name for name in names if name], "level": len(match.group(1)), "line": 1})
    return found


def _parent_edges(edges: dict[str, set[str]], files: set[str]) -> dict[str, set[str]]:
    """Importing pkg.sub.mod runs pkg/__init__.py and pkg/sub/__init__.py first, and a test under a folder gets that folder's conftest.py."""
    reach: dict[str, set[str]] = defaultdict(set)
    for source, targets in edges.items():
        reach[source].update(targets)
        for target in targets:
            parts = target.split("/")[:-1]
            for depth in range(1, len(parts) + 1):
                parent = "/".join(parts[:depth]) + "/__init__.py"
                if parent in files and parent != source:
                    reach[source].add(parent)
    tests = [path for path in files if path.endswith(".py") and is_test_path(path)]
    for conftest in (path for path in files if path.rsplit("/", 1)[-1] == "conftest.py"):
        prefix = conftest[:-len("conftest.py")]
        for test in tests:
            if test != conftest and test.startswith(prefix):
                reach[test].add(conftest)
    return reach


def _reversed(edges: dict[str, set[str]]) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            reverse[target].add(source)
    return reverse


def _strip_json_comments(text: str) -> str:
    return re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', lambda match: match.group(1) or "", text, flags=re.S)


def _js_alias_edges(root: Path, project: Project, files: list[str], add) -> None:
    """Imports that don't look relative but reach a sibling: workspace package names and tsconfig paths."""
    packages: dict[str, str] = {}
    aliases: list[tuple[str, str, str]] = []
    for path in files:
        name = path.rsplit("/", 1)[-1]
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        if name == "package.json":
            try:
                manifest = json.loads(filesystem.read_text(root / path) or "{}")
            except ValueError:
                continue
            if isinstance(manifest, dict) and isinstance(manifest.get("name"), str):
                packages[manifest["name"]] = folder
        elif name in ("tsconfig.json", "jsconfig.json", "tsconfig.base.json"):
            try:
                options = (json.loads(_strip_json_comments(filesystem.read_text(root / path) or "{}")) or {}).get("compilerOptions") or {}
            except (ValueError, AttributeError):
                continue
            if not isinstance(options, dict) or not isinstance(options.get("paths") or {}, dict):
                continue
            base = _normal([*folder.split("/"), *str(options.get("baseUrl") or ".").split("/")])
            for pattern, targets in (options.get("paths") or {}).items():
                if isinstance(targets, list) and targets and isinstance(targets[0], str):
                    aliases.append((pattern, targets[0], base))
            if options.get("baseUrl"):
                aliases.append(("*", "*", base))
    if not packages and not aliases:
        return
    for path, language in project.languages.items():
        if language not in ("javascript", "typescript"):
            continue
        for item in (project.facts.get(path) or {}).get("imports", []):
            module = item["module"]
            if module.startswith("."):
                continue
            target = _resolve_alias(project, module, packages, aliases)
            if target and target != path:
                add(path, target)


def _resolve_alias(project: Project, module: str, packages: dict[str, str], aliases: list[tuple[str, str, str]]) -> str | None:
    head = "/".join(module.split("/")[:2]) if module.startswith("@") else module.split("/")[0]
    if head in packages:
        rest = module[len(head):].lstrip("/")
        for candidate in ([f"{packages[head]}/{rest}", f"{packages[head]}/src/{rest}"] if rest else [f"{packages[head]}/src/index", f"{packages[head]}/index", f"{packages[head]}/lib/index"]):
            found = project._resolve_js("x", candidate.lstrip("/"))
            if found:
                return found
    for pattern, replacement, base in aliases:
        prefix, star, suffix = pattern.partition("*")
        if star and module.startswith(prefix) and module.endswith(suffix) and len(module) >= len(prefix) + len(suffix):
            middle = module[len(prefix):len(module) - len(suffix)]
            found = project._resolve_js("x", "/".join(part for part in (base, replacement.replace("*", middle)) if part))
            if found:
                return found
        elif not star and module == pattern:
            found = project._resolve_js("x", "/".join(part for part in (base, replacement) if part))
            if found:
                return found
    return None


def build(root: Path) -> Graph:
    project, records = _load(root)
    files = list(records)
    unread = _imports_by_pattern(project, root, records)
    edges: dict[str, set[str]] = defaultdict(set)

    def add(source: str, target: str) -> None:
        if source != target:
            edges[source].add(target)

    ambiguous = _python_edges(project, add)
    for source, targets in project._build_graph(include_optional=True).items():  # relative JS and TS, which the scanner already traces
        if project.languages.get(source) in ("javascript", "typescript"):
            edges[source].update(targets)
    _go_edges(root, files, add)
    _jvm_edges(root, files, records, add)
    _c_edges(root, files, add)
    _rust_edges(root, files, add)
    _shell_edges(root, files, project.languages, add)
    _js_alias_edges(root, project, files, add)
    reach = _parent_edges(edges, set(files))
    by_name = _mention_edges(root, project)
    for test, scripts in by_name.items():
        reach[test].update(scripts)
    inline, _ = search(root, _INLINE_TESTS, None, only=lambda path: path.endswith(".rs"))
    untraced = Counter(language for language in project.languages.values() if language and language not in TRACED and language != "html" and language != "sql")
    return Graph(dict(edges), _reversed(edges), dict(reach), _reversed(reach), project, untraced, records, ambiguous, sorted(unread), by_name, {hit.path for hit in inline})


def _reach(graph: dict[str, set[str]], starts: list[str]) -> dict[str, int]:
    """Every node reachable, with how many steps it took. Iterative, because real import chains get deep."""
    distance = {start: 0 for start in starts}
    queue = deque(starts)
    while queue:
        node = queue.popleft()
        for neighbor in graph.get(node, ()):
            if neighbor not in distance:
                distance[neighbor] = distance[node] + 1
                queue.append(neighbor)
    return distance


def _caveat(data: dict) -> str:
    untraced = data.get("untraced") or {}
    note = "Read from text and syntax, so dynamic imports, plugin registration, configuration-driven wiring and tests that reach code only over a network don't show."
    if untraced:
        note += f" Not traced at all: {', '.join(f'{name} ({count})' for name, count in untraced.items())}."
    if data.get("ambiguous"):
        note += f" {data['ambiguous']} imports could mean several same-named files, and all of them were counted."
    if data.get("unread"):
        note += f" {len(data['unread'])} source files were too large to read, so their imports are missing, such as {data['unread'][0]}."
    return note


def _facts_note(built: Graph) -> dict:
    return {"untraced": dict(built.untraced), "ambiguous": built.ambiguous, "unread": built.unread[:20]}


# ---------------------------------------------------------------- graph

def graph_overview(root: Path, top: int) -> dict:
    built = build(root)
    edges, reverse = built.edges, built.reverse
    # Importing anything in a package touches its __init__.py, so an empty one would top the list and say nothing.
    fan_in = Counter({path: len(targets) for path, targets in reverse.items() if not (path.endswith("__init__.py") and built.project.lines.get(path, 0) < 5)})
    fan_out = Counter({path: len(targets) for path, targets in edges.items()})
    cycles = sorted((sorted(component) for component in strongly_connected(edges) if len(component) >= 2), key=lambda component: -len(component))
    folder_edges: Counter = Counter()
    for source, targets in edges.items():
        for target in targets:
            a, b = source.split("/")[0] if "/" in source else ".", target.split("/")[0] if "/" in target else "."
            if a != b:
                folder_edges[(a, b)] += 1
    folder_loops = sorted({tuple(sorted(pair)) for pair in folder_edges if (pair[1], pair[0]) in folder_edges})
    traced = [path for path, language in built.project.languages.items() if language in TRACED]
    unreached = sorted(path for path in traced if path not in reverse and not is_test_path(path) and not is_script_path(path) and not path.endswith(("__init__.py", "__main__.py", "main.go", "setup.py", "conftest.py")) and path in edges)
    return {"files_traced": len(traced), "edges": sum(len(targets) for targets in edges.values()), **_facts_note(built),
            "most_depended_on": fan_in.most_common(top), "most_dependencies": fan_out.most_common(top), "cycles_total": len(cycles), "cycles": [{"size": len(c), "members": c[:8]} for c in cycles[:top]],
            "folder_edges": [{"from": a, "to": b, "imports": count} for (a, b), count in folder_edges.most_common(top)], "folder_loops": folder_loops[:top],
            "nothing_imports": unreached[:top], "nothing_imports_total": len(unreached)}


def render_graph_overview(data: dict) -> str:
    out = [f"{data['edges']:,} import edges across {data['files_traced']:,} files. {_caveat(data)}"]
    if data["most_depended_on"]:
        out += ["", "Most depended on. A change here reaches furthest:"] + [f"  {count:>5}  {path}" for path, count in data["most_depended_on"]]
    if data["most_dependencies"]:
        out += ["", "Most dependencies. Hardest to test alone:"] + [f"  {count:>5}  {path}" for path, count in data["most_dependencies"]]
    out += ["", f"Import cycles: {data['cycles_total']}."] + [f"  {row['size']} files: {', '.join(row['members'])}" for row in data["cycles"]]
    if data["folder_edges"]:
        out += ["", "Between top-level folders:"] + [f"  {row['imports']:>5}  {row['from']} -> {row['to']}" for row in data["folder_edges"]]
    if data["folder_loops"]:
        out += ["", "Top-level folders that import each other, so neither is a layer below the other:"] + [f"  {a} <-> {b}" for a, b in data["folder_loops"]]
    if data["nothing_imports_total"]:
        out += ["", f"Import others, and nothing imports them ({data['nothing_imports_total']:,}). Entry points look like this, and so does dead code:"]
        out += [f"  {path}" for path in data["nothing_imports"]] + more(data["nothing_imports_total"] - len(data["nothing_imports"]))
    return "\n".join(out)


def graph_file(root: Path, target: str, top: int) -> dict:
    built = build(root)
    path = relative_path(root, target)
    language = built.project.languages.get(path)
    dependents = _reach(built.reach_reverse, [path])
    dependencies = _reach(built.reach, [path])
    externals = sorted({item["module"].split(".")[0] for item in (built.project.facts.get(path) or {}).get("imports", []) if not item.get("level") and not item["module"].startswith(".")}
                       - {t.split("/")[0] for t in built.edges.get(path, ())})
    cycle = next((sorted(component) for component in strongly_connected(built.edges) if path in component and len(component) >= 2), None)
    return {"path": path, "language": language, "traced": language in TRACED, **_facts_note(built), "imports": sorted(built.edges.get(path, ()))[:top], "imports_total": len(built.edges.get(path, ())),
            "imported_by": sorted(built.reverse.get(path, ()))[:top], "imported_by_total": len(built.reverse.get(path, ())),
            "transitive_dependents": max(0, len(dependents) - 1), "transitive_dependencies": max(0, len(dependencies) - 1), "external": externals[:top], "cycle": cycle}


def render_graph_file(data: dict) -> str:
    if not data["language"]:
        return f"{data['path']} isn't source code in a language these tools read."
    if not data["traced"]:
        return f"{data['path']} is {data['language']}, whose imports aren't traced here. Use `occam query find` on its names instead."
    out = [f"{data['path']}: imports {data['imports_total']} files here, imported by {data['imported_by_total']}. Reached by {data['transitive_dependents']} files through others, and reaches {data['transitive_dependencies']}.", _caveat(data)]
    if data["imports"]:
        out += ["", "Imports:"] + [f"  {path}" for path in data["imports"]] + more(data["imports_total"] - len(data["imports"]))
    if data["imported_by"]:
        out += ["", "Imported by:"] + [f"  {path}" for path in data["imported_by"]] + more(data["imported_by_total"] - len(data["imported_by"]))
    if data["external"]:
        out += ["", f"Outside this repository: {', '.join(data['external'])}"]
    if data["cycle"]:
        out += ["", f"In an import cycle with: {', '.join(data['cycle'][:8])}"]
    return "\n".join(out)


# ---------------------------------------------------------------- impact

_TEST_NAME_FORMS = ("test_{}", "{}_test", "{}.test", "{}.spec", "{}Test", "{}Tests", "{}_spec", "Test{}")


def _named_after(stem: str, tests: list[str]) -> list[str]:
    forms = {form.format(stem) for form in _TEST_NAME_FORMS}
    return [path for path in tests if path.rsplit("/", 1)[-1].rsplit(".", 1)[0] in forms]


def impact(root: Path, targets: list[str] | None, changed: bool, base: str | None, top: int) -> dict:
    """What a change reaches, and which tests to run, so a giant suite needn't run for a one-file change."""
    seeds, gone = _seeds(root, targets, changed, base)
    built = build(root)
    languages = built.project.languages
    code_seeds = [path for path in seeds if languages.get(path) in TRACED]
    not_code = [path for path in seeds if not languages.get(path)]
    not_traced = [path for path in seeds if languages.get(path) and languages.get(path) not in TRACED]
    reached = _reach(built.reach_reverse, code_seeds)
    dependents = sorted((path for path, steps in reached.items() if steps > 0), key=lambda path: (reached[path], path))
    source = [path for path in dependents if not is_test_path(path)]
    direct = sorted(path for path in dependents if reached[path] == 1 and path in built.reverse and path not in built.by_name)
    all_tests = [path for path, language in languages.items() if language and _runnable_test(path)]
    known = set(dependents) | set(seeds)
    mentions = _mentions(root, [path for path in [*code_seeds, *gone] if not is_test_path(path)], known)
    tests_gone = sorted({row["path"] for row in mentions if row["seed"] in gone and _runnable_test(row["path"])})
    by_import = [path for path in dependents if _runnable_test(path)]
    by_file_name = sorted({test for seed in [*seeds, *gone] for test in _named_after(_stem(seed), all_tests)} - set(by_import))
    in_place = sorted(path for path in code_seeds if path in built.inline_tests or (reached.get(path) is not None and path in built.inline_tests))
    in_place += sorted(path for path in source if path in built.inline_tests)
    tests = list(dict.fromkeys([*(path for path in seeds if _runnable_test(path)), *by_import, *in_place, *by_file_name, *tests_gone]))
    by_script = sorted(path for path in tests if built.by_name.get(path, set()) & set(reached))
    return {"seeds": seeds, "gone": gone, "direct": direct[:top], "direct_total": len(direct), "source": source[:top], "source_total": len(source),
            "tests": tests[:top], "tests_total": len(tests), "tests_by_name": by_file_name[:top], "tests_by_script": by_script[:top], "tests_naming_what_went": tests_gone[:top], "tests_in_place": in_place[:top],
            "all_tests": len(all_tests), "high_consequence": [path for path in source if _CONSEQUENCE.search(path)][:top], "not_code": not_code[:top], "not_code_total": len(not_code), "not_traced": not_traced[:top],
            "mentions": mentions[:top], "mentions_total": len(mentions), **_facts_note(built)}


def _runnable_test(path: str) -> bool:
    """conftest.py and __init__.py live among tests, but asking a runner to run one runs nothing."""
    return is_test_path(path) and path.rsplit("/", 1)[-1] not in ("conftest.py", "__init__.py")


def _seeds(root: Path, targets: list[str] | None, changed: bool, base: str | None) -> tuple[list[str], list[str]]:
    """What changed, and which of those paths are gone from disk, whose importers no longer resolve to anything."""
    if changed or base:
        lines = filesystem.changed_lines(root, base)
        if lines is None:
            raise filesystem.GitProblem("Finding what changed needs git")
        deleted, renamed = filesystem.removed_and_renamed(root, base)
        gone = sorted({*deleted, *renamed.values()})
        return sorted(set(lines) - set(gone)), gone
    return selected_files(root, targets), []


def _mentions(root: Path, seeds: list[str], known: set[str]) -> list[dict]:
    """Files that name a changed module in text without importing it: mock targets, config, registries, plugin lists."""
    found: dict[str, dict] = {}
    for seed in seeds[:50]:
        stem = _stem(seed)
        if stem in ("__init__", "index", "main", "mod", "lib") or len(stem) < 4:
            continue
        hits, _ = search(root, stem, None, fixed=True, word=True)
        for hit in hits:
            if hit.path not in known and hit.path not in found:
                found[hit.path] = {"where": f"{hit.path}:{hit.line}", "path": hit.path, "seed": seed, "text": safe_line(hit.text)}
    return sorted(found.values(), key=lambda row: row["where"])


def render_impact(data: dict) -> str:
    if not data["seeds"] and not data["gone"]:
        return "Nothing to trace: no paths named and no changes found."
    every_seed = [*data["seeds"], *data["gone"]]
    shown_seeds = ", ".join(every_seed[:6]) + (f" and {len(every_seed) - 6} more" if len(every_seed) > 6 else "")
    out = [f"From {shown_seeds}: {data['source_total']:,} other source files and {data['tests_total']:,} of {data['all_tests']:,} test files reachable.", _caveat(data)]
    if data["gone"]:
        out += ["", f"Removed or renamed away, so nothing resolves to them now, and only text can show who still needs them: {', '.join(data['gone'][:10])}"]
        if data["tests_naming_what_went"]:
            out.append(f"  These tests still name them: {', '.join(data['tests_naming_what_went'])}")
    if data["not_code"]:
        out += ["", f"Not code, so not traced. A config or data change can reach anything: {', '.join(data['not_code'])}"] + more(data["not_code_total"] - len(data["not_code"]))
    if data["not_traced"]:
        out += ["", f"In languages not traced here, so what they reach is unknown: {', '.join(data['not_traced'])}"]
    if data["tests"]:
        out += ["", "Tests to run, nearest first:"] + [f"  {path}" for path in data["tests"]] + more(data["tests_total"] - len(data["tests"]))
        if data["tests_by_name"]:
            out.append(f"  ({len(data['tests_by_name'])} of those by their file name alone, with no import seen.)")
        if data["tests_by_script"]:
            out.append(f"  ({len(data['tests_by_script'])} of those because they name a script in their code, with no import seen.)")
        if data["tests_in_place"]:
            out.append(f"  ({len(data['tests_in_place'])} of those carry their tests inside the source file.)")
    else:
        out += ["", "No test reaches this, by imports or by name. Nothing here shows it's protected."]
    if data["high_consequence"]:
        out += ["", "Reached code that handles something high consequence:"] + [f"  {path}" for path in data["high_consequence"]]
    if data["direct"]:
        out += ["", f"Direct dependents ({data['direct_total']:,}):"] + [f"  {path}" for path in data["direct"]] + more(data["direct_total"] - len(data["direct"]))
    if data["source_total"] > data["direct_total"]:
        out += ["", f"All dependents ({data['source_total']:,}), nearest first:"] + [f"  {path}" for path in data["source"]] + more(data["source_total"] - len(data["source"]))
    if data["mentions"]:
        out += ["", f"Name it in text without importing it ({data['mentions_total']:,}). Mock targets, config and registries break at runtime:"]
        out += [f"  {row['where']}  {row['text']}" for row in data["mentions"]] + more(data["mentions_total"] - len(data["mentions"]))
    return "\n".join(out)


# ---------------------------------------------------------------- tests

_COBERTURA_FILE = re.compile(r'\bfilename="([^"]+)"')
_COBERTURA_RATE = re.compile(r'\bline-rate="(\d+(?:\.\d+)?)"')
_COVERAGE_FILES = ("coverage.xml", "cobertura.xml", "coverage/cobertura-coverage.xml", "coverage.json", "lcov.info", "coverage/lcov.info", "cover.out", "coverage.out")


def _read_coverage(root: Path) -> dict | None:
    """Line rates from a report an earlier run left behind. This is data from the repository, and it can be stale, so its age comes with it."""
    for name in _COVERAGE_FILES:
        path = root / name
        text = filesystem.read_text(path)
        if text is None:
            continue
        rates = _coverage_rates(name, text)
        if rates:
            return {"file": name, "modified": int(path.stat().st_mtime), "rates": rates}
    return None


def _coverage_rates(name: str, text: str) -> dict[str, float]:
    if name.endswith(".xml"):  # by hand, since parsing a repository's XML invites entity expansion. Each tag gets a bounded look
        rates = {}
        for tag in text.split("<class ")[1:]:
            head = tag[:2000]
            filename, rate = _COBERTURA_FILE.search(head), _COBERTURA_RATE.search(head)
            if filename and rate:
                rates[filename.group(1)] = float(rate.group(1))
        return rates
    if name.endswith(".json"):
        try:
            files = json.loads(text).get("files") or {}
            return {path: (row.get("summary") or {}).get("percent_covered", 0) / 100 for path, row in files.items() if isinstance(row, dict)}
        except (ValueError, AttributeError, TypeError):
            return {}
    if name.endswith(".info"):
        rates = {}
        for record in text.split("end_of_record"):
            source = re.search(r"^SF:(.+)$", record, re.M)
            found = re.search(r"^LF:(\d+)$", record, re.M)
            hit = re.search(r"^LH:(\d+)$", record, re.M)
            if source and found and hit and int(found.group(1)):
                rates[source.group(1)] = int(hit.group(1)) / int(found.group(1))
        return rates
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for match in re.finditer(r"^(\S+?):\d+\.\d+,\d+\.\d+ (\d+) (\d+)$", text, re.M):
        totals[match.group(1)][0] += int(match.group(2))
        totals[match.group(1)][1] += int(match.group(2)) if int(match.group(3)) else 0
    return {path: covered / statements for path, (statements, covered) in totals.items() if statements}


def tests_overview(root: Path, top: int) -> dict:
    built = build(root)
    project = built.project
    sources = [path for path, language in project.languages.items() if language in TRACED and not is_test_path(path) and (project.lines.get(path, 0) >= 15 or _CONSEQUENCE.search(path))]
    tests = [path for path, language in project.languages.items() if language and is_test_path(path)]
    reached = _reach(built.reach, [*tests, *built.inline_tests])
    project._imported_by = built.reverse
    untested_direct = project.untested_modules()
    no_reach = [path for path in sources if path not in reached]
    no_reach.sort(key=lambda path: (not _CONSEQUENCE.search(path), -project.lines.get(path, 0)))
    functions = sum(1 for path in tests for item in (project.facts.get(path) or {}).get("defs", []) if re.match(r"test|Test", item["name"]))
    test_lines = sum(project.lines.get(path, 0) for path in tests)
    source_lines = sum(project.lines.get(path, 0) for path in sources)
    coverage = _read_coverage(root)
    low = []
    if coverage:
        known = {path: rate for path, rate in coverage["rates"].items()}
        low = sorted(((rate, path) for path, rate in known.items() if not is_test_path(path)))[:top]
    return {"test_files": len(tests), "test_functions": functions, "test_lines": test_lines, "source_lines": source_lines, "source_files": len(sources), "reached_by_tests": sum(1 for path in sources if path in reached),
            "no_test_reaches": [{"path": path, "lines": project.lines.get(path, 0), "high_consequence": bool(_CONSEQUENCE.search(path))} for path in no_reach[:top]], "no_test_reaches_total": len(no_reach),
            "no_direct_test": [{"path": row[0], "lines": row[1], "high_consequence": row[2]} for row in untested_direct[:top]], "no_direct_test_total": len(untested_direct),
            "coverage": {"file": coverage["file"], "modified": coverage["modified"], "files": len(coverage["rates"]), "lowest": [{"path": path, "rate": round(rate, 3)} for rate, path in low]} if coverage else None,
            **_facts_note(built)}


def render_tests_overview(data: dict) -> str:
    out = [f"{data['test_files']:,} test files, {data['test_functions']:,} test functions counted in Python and braced languages, {data['test_lines']:,} test lines against {data['source_lines']:,} source lines.",
           f"Tests reach {data['reached_by_tests']:,} of {data['source_files']:,} source files through imports, not counting files under 15 lines unless they handle something high consequence. Reaching a file isn't checking it. `occam mutate` shows that for Python.", _caveat(data)]
    if data["no_test_reaches"]:
        out += ["", f"No test reaches these, even indirectly ({data['no_test_reaches_total']:,}), consequence first:"]
        out += [f"  {row['lines']:>6}  {row['path']}{'  high consequence' if row['high_consequence'] else ''}" for row in data["no_test_reaches"]] + more(data["no_test_reaches_total"] - len(data["no_test_reaches"]))
    if data["no_direct_test"]:
        out += ["", f"No test names these directly ({data['no_direct_test_total']:,}):"]
        out += [f"  {row['lines']:>6}  {row['path']}{'  high consequence' if row['high_consequence'] else ''}" for row in data["no_direct_test"]] + more(data["no_direct_test_total"] - len(data["no_direct_test"]))
    coverage = data["coverage"]
    if coverage:
        import datetime as dt
        when = dt.datetime.fromtimestamp(coverage["modified"], dt.timezone.utc).strftime("%Y-%m-%d")
        out += ["", f"From {coverage['file']}, written {when}, a report an earlier run left, so it may be stale. Lowest line coverage of {coverage['files']:,} files:"]
        out += [f"  {100 * row['rate']:>5.1f}%  {row['path']}" for row in coverage["lowest"]]
    else:
        out += ["", "No coverage report here. Executed isn't checked, but it does show what never ran, so see the Python auditing reference or your runner's coverage flag."]
    return "\n".join(out)


def tests_for(root: Path, targets: list[str], top: int) -> dict:
    data = impact(root, targets, False, None, top)
    return {key: data[key] for key in ("seeds", "tests", "tests_total", "all_tests", "tests_by_name", "tests_by_script", "not_traced", "not_code", "untraced", "ambiguous", "unread")}


def render_tests_for(data: dict) -> str:
    out = [f"{data['tests_total']:,} of {data['all_tests']:,} test files reach {', '.join(data['seeds'][:4])}{' and more' if len(data['seeds']) > 4 else ''}, by import or by name.", _caveat(data)]
    named_script = set(data["tests_by_script"])
    if data["not_traced"] or data["not_code"]:
        out.append(f"Can't be traced: {', '.join([*data['not_traced'], *data['not_code']])}.")
    if data["tests"]:
        out += [f"  {path}" + ("  (by its file name alone)" if path in data["tests_by_name"] else "  (names a script, with no import seen)" if path in named_script else "") for path in data["tests"]] + more(data["tests_total"] - len(data["tests"]))
    else:
        out.append("No test reaches this. Nothing here shows it's protected.")
    return "\n".join(out)
