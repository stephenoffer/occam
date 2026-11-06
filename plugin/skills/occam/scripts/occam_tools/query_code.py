"""Questions about the code itself: what's in this file, where is this name used, what's biggest, what's public, what touches the outside world."""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import files as filesystem, rules_text
from .py_helpers import _complexity, _decorator_names
from .query import WORD_END, WORD_START, BadQuestion, Hit, Views, enclosing, hits_by_file, language_at, line_of, more, safe_line, search, selected_files, shown
from .scan import Cache, _analyze_all, analyze_text
from .source import is_script_path, is_test_path, load

# ---------------------------------------------------------------- outline

MAX_SIGNATURE = 120
_SHELL_FUNCTION = re.compile(r"^[ \t]*(?:function[ \t]+([\w:.-]+)[ \t]*(?:\(\))?|([\w:.-]+)[ \t]*\(\))[ \t\n]*\{?", re.M)
_OTHER_SYMBOLS = {
    "ruby": re.compile(r"^[ \t]*(?:(def)[ \t]+([\w.?!=]+)|(class|module)[ \t]+(\w+))", re.M),
    "perl": re.compile(r"^[ \t]*(sub)[ \t]+(\w+)|^[ \t]*(package)[ \t]+([\w:]+)", re.M),
    "lua": re.compile(r"^[ \t]*(?:local[ \t]+)?(function)[ \t]+([\w.:]+)", re.M),
    "elixir": re.compile(r"^[ \t]*(defp?|defmacro)[ \t]+(\w+)|^[ \t]*(defmodule)[ \t]+([\w.]+)", re.M),
    "sql": re.compile(r"^[ \t]*CREATE[ \t]+(?:OR[ \t]+REPLACE[ \t]+)?(?:TEMP(?:ORARY)?[ \t]+)?(TABLE|VIEW|FUNCTION|PROCEDURE|INDEX|TRIGGER|TYPE)[ \t]+(?:IF[ \t]+NOT[ \t]+EXISTS[ \t]+)?([\w.\"]+)", re.M | re.I),
    "terraform": re.compile(r"^(resource|module|data|variable|output)[ \t]+\"?([\w-]+)\"?(?:[ \t]+\"([\w-]+)\")?", re.M),
}


def _signature(node: ast.AST) -> str:
    try:
        text = ast.unparse(node.args)
    except (AttributeError, ValueError, RecursionError):
        text = "..."
    returns = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) is not None else ""
    full = f"({text}){returns}"
    return full if len(full) <= MAX_SIGNATURE else full[:MAX_SIGNATURE] + "..."


def _python_symbols(tree: ast.AST) -> list[dict]:
    found: list[dict] = []

    def walk(body: list, depth: int, owner: str | None) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                bases = ", ".join(ast.unparse(base) for base in node.bases)
                found.append({"kind": "class", "name": node.name, "line": node.lineno, "end": node.end_lineno, "depth": depth, "signature": f"({bases})" if bases else "",
                              "decorators": _decorator_names(node), "doc": _first_line(ast.get_docstring(node))})
                walk(node.body, depth + 1, node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if owner else "function"
                found.append({"kind": ("async " if isinstance(node, ast.AsyncFunctionDef) else "") + kind, "name": node.name, "line": node.lineno, "end": node.end_lineno, "depth": depth,
                              "signature": _signature(node), "complexity": _complexity(node), "decorators": _decorator_names(node), "doc": _first_line(ast.get_docstring(node))})
                walk(node.body, depth + 1, None)
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(node, field, []), depth, owner)
                for handler in getattr(node, "handlers", []):
                    walk(handler.body, depth, owner)

    walk(getattr(tree, "body", []), 0, None)
    return found


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().split("\n", 1)[0][:100]


def _text_symbols(path: str, text: str, language: str) -> list[dict]:
    source = load(path, text, language)
    found: list[dict] = []
    if language == "shell":
        for match in _SHELL_FUNCTION.finditer(source.code):
            found.append({"kind": "function", "name": match.group(1) or match.group(2), "line": source.line_of(match.start()), "depth": 0})
    elif language in _OTHER_SYMBOLS:
        for match in _OTHER_SYMBOLS[language].finditer(source.code):
            groups = [group for group in match.groups() if group]
            found.append({"kind": groups[0].lower(), "name": " ".join(groups[1:]), "line": source.line_of(match.start()), "depth": 0})
    else:
        structured, facts = rules_text.structure_findings(source, False)
        del structured
        found += [{"kind": item["kind"], "name": item["name"], "line": item["line"], "depth": 0} for item in facts["classes"]]
        found += [{"kind": "function", "name": item["name"], "line": item["line"], "end": item["end"], "depth": 0, "complexity": item.get("complexity")} for item in facts["defs"]]
    return sorted(found, key=lambda item: item["line"])


def _notebook_symbols(path: str, text: str) -> list[dict]:
    """A notebook's code cells, read as one program the way the scanner reads them. Lines count through the joined cells."""
    facts = analyze_text(path, text).get("facts") or {}
    found = [{"kind": "class", "name": item["name"], "line": item["line"], "depth": 0} for item in facts.get("classes", [])]
    found += [{"kind": item["kind"], "name": item["name"], "line": item["line"], "end": item.get("end"), "depth": 1 if item.get("class") else 0, "complexity": item.get("complexity")} for item in facts.get("defs", [])]
    return sorted(found, key=lambda item: item["line"])


def outline(root: Path, targets: list[str], top: int) -> dict:
    """Symbols with line ranges, so a large file can be read by the part that matters."""
    results = []
    for path in selected_files(root, targets):
        language = language_at(root, path)
        text = filesystem.read_text(root / path) if language else None
        if text is None:
            continue
        row = {"path": path, "language": language, "lines": text.count("\n") + 1, "symbols": [], "parse_error": None}
        if language == "python":
            try:
                row["symbols"] = _python_symbols(ast.parse(text))
            except (SyntaxError, ValueError, RecursionError) as error:
                row["parse_error"] = str(error)
        elif language == "notebook":
            row["symbols"] = _notebook_symbols(path, text)
        else:
            row["symbols"] = _text_symbols(path, text, language)
        results.append(row)
    return {"files": results, "top": top}


def render_outline(data: dict) -> str:
    if not data["files"]:
        return "No source files in those paths."
    out = []
    for row in data["files"]:
        out.append(f"{row['path']}  ({row['lines']:,} lines, {row['language']})")
        if row["parse_error"]:
            out.append(f"  doesn't parse on this Python: {row['parse_error'][:120]}")
        symbols, left = shown(row["symbols"], data["top"])
        for symbol in symbols:
            span = f"{symbol['line']}-{symbol['end']}" if symbol.get("end") else str(symbol["line"])
            decorated = "".join(f"@{name} " for name in symbol.get("decorators") or [])
            size = f"  complexity {symbol['complexity']}" if symbol.get("complexity") and symbol["complexity"] >= 10 else ""
            doc = f"  # {symbol['doc']}" if symbol.get("doc") else ""
            out.append(f"  {span:>11}  {'  ' * symbol['depth']}{decorated}{symbol['kind']} {symbol['name']}{symbol.get('signature', '')}{size}{doc}")
        out += more(left)
    return "\n".join(out)


# ---------------------------------------------------------------- find

_DEFINES = r"(?:def|class|func|fn|function|interface|struct|type|enum|trait|module|sub|const|let|var|val|impl)"
_DYNAMIC = re.compile(r"\b(?:getattr|importlib|__import__|eval|exec|globals|reflect\.|Class\.forName|require\(\s*[a-zA-Z_])")
_TEXT_FILES = re.compile(r"\.(?:md|rst|txt|ya?ml|toml|json|ini|cfg|conf|xml|env|lock|csv)$|(?:^|/)(?:Makefile|Dockerfile[^/]*)$", re.I)
MAX_FILES_CLASSIFIED = 5000


def _python_roles(tree: ast.AST, name: str) -> dict[int, str]:
    """Line to role for one parsed file. Text can't tell a call from a mention, and the tree can."""
    roles: dict[int, str] = {}
    rank = {"definition": 4, "import": 3, "call": 2, "reference": 1}

    def note(line: int, role: str) -> None:
        if rank[role] > rank.get(roles.get(line, ""), 0):
            roles[line] = role

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            note(node.lineno, "definition")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] + [alias.asname or "" for alias in node.names] + [getattr(node, "module", "") or ""]
            if any(name in part.split(".") for part in names):
                note(node.lineno, "import")
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if called == name:
                note(getattr(func, "end_lineno", None) or node.lineno, "call")
        elif isinstance(node, ast.Name) and node.id == name:
            note(node.lineno, "definition" if isinstance(node.ctx, ast.Store) and getattr(node, "col_offset", 1) == 0 else "reference")
        elif isinstance(node, ast.Attribute) and node.attr == name:
            note(getattr(node, "end_lineno", None) or node.lineno, "reference")
        elif isinstance(node, ast.arg) and node.arg == name:
            note(node.lineno, "reference")
    return roles


def _role_in_text(line: str, column: int, name: str) -> str:
    if re.search(rf"\b{_DEFINES}\s+(?:\([^)]*\)\s*)?{re.escape(name)}\b", line):
        return "definition"
    if re.match(r"\s*(?:import|from|use|using|require|include|#include|package)\b", line):
        return "import"
    return "call" if line[column + len(name):].lstrip().startswith("(") else "reference"


class _Classifier:
    """Sorts the lines a search found into what they are, reading only the files it hit."""

    def __init__(self, root: Path, name: str) -> None:
        self.root, self.name = root, name
        self.views = Views(root)
        self._python: dict[str, tuple[dict[int, str], list[dict]] | None] = {}

    def _python_facts(self, path: str, source) -> tuple[dict[int, str], list[dict]] | None:
        if path not in self._python:
            try:
                tree = ast.parse(source.text)
            except (SyntaxError, ValueError, RecursionError):
                self._python[path] = None
            else:
                defs = [{"name": node.name, "line": node.lineno, "end": node.end_lineno, "class": None} for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
                self._python[path] = (_python_roles(tree, self.name), defs)
        return self._python[path]

    def classify(self, hit: Hit) -> dict:
        word = re.search(rf"(?<![A-Za-z0-9_]){re.escape(self.name)}(?![A-Za-z0-9_])", hit.text)
        column = word.start() if word else 0
        role, inside = None, None
        source = self.views.source(hit.path)
        kind = self.views.kind_at(hit.path, hit.line, column)
        if kind == "code" and source is not None:
            if source.language == "python":
                facts = self._python_facts(hit.path, source)
                if facts:
                    role = facts[0].get(hit.line, "reference")
                    inside = enclosing(facts[1], hit.line)
            role = role or _role_in_text(line_of(source.code, source, hit.line), column, self.name)
        else:
            role = "comment" if kind == "comment" else "string" if kind == "string" else "text"
        return {"where": f"{hit.path}:{hit.line}", "path": hit.path, "line": hit.line, "role": role, "inside": inside, "test": is_test_path(hit.path), "text": safe_line(hit.text)}


def find(root: Path, name: str, targets: list[str] | None, top: int) -> dict:
    """Where a name is defined, imported, called and mentioned. Dotted names look up the last part, and strings keep the dotted form findable."""
    last = name.rsplit(".", 1)[-1]
    hits, stopped = search(root, last, targets, fixed=True, word=True)
    per_file = Counter(hit.path for hit in hits)
    classifier = _Classifier(root, last)
    readable = {path for path, _ in per_file.most_common(MAX_FILES_CLASSIFIED)}
    rows = [classifier.classify(hit) for hit in hits if hit.path in readable]
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[("test " if row["test"] and row["role"] in ("call", "reference", "import") else "") + row["role"]].append(row)
    references = sum(len(rows) for role, rows in groups.items() if role not in ("definition", "comment", "text"))
    dynamic = None
    if not references:
        hits_dynamic, _ = search(root, r"getattr\(|importlib|__import__|globals\(\)|reflect\.|Class\.forName", targets, limit=1)
        dynamic = bool(hits_dynamic)
    return {"name": name, "searched": last, "total": len(hits), "files": len(per_file), "stopped_at_limit": stopped, "files_not_classified": max(0, len(per_file) - len(readable)),
            "counts": {role: len(items) for role, items in groups.items()}, "groups": {role: items[:top] for role, items in groups.items()},
            "top_files": per_file.most_common(10), "references": references, "dynamic_use_exists": dynamic}


_ORDER = (("definition", "Defined"), ("import", "Imported"), ("call", "Called"), ("reference", "Referenced"), ("string", "In strings, which break at runtime rather than at import: mock targets, registries, config keys"),
          ("test import", "Imported by tests"), ("test call", "Called by tests"), ("test reference", "Referenced by tests"), ("text", "In other files: docs and config"), ("comment", "In comments"))


def render_find(data: dict) -> str:
    out = [f"'{data['name']}': {data['total']:,} lines in {data['files']:,} files." + (f" Searched for the last part, '{data['searched']}'." if data["name"] != data["searched"] else "")]
    if data["stopped_at_limit"]:
        out.append("Stopped at the search limit, so this is a sample. Narrow it with a path.")
    if data["files_not_classified"]:
        out.append(f"{data['files_not_classified']:,} files weren't sorted, because there were too many. Narrow it with a path.")
    for role, title in _ORDER:
        items = data["groups"].get(role)
        if items:
            out += ["", f"{title} ({data['counts'][role]:,}):"]
            out += [f"  {row['where']}" + (f"  in {row['inside']}" if row.get("inside") and role != "definition" else "") + f"  {row['text']}" for row in items]
            out += more(data["counts"][role] - len(items))
    if not data["references"] and data["total"] is not None:
        out += ["", "Nothing refers to this in code, as far as text and syntax can show. That doesn't prove it unused: "
                + ("this code uses dynamic lookups, so check those." if data["dynamic_use_exists"] else "check public API, configuration and framework registration.")]
    return "\n".join(out)


# ---------------------------------------------------------------- grep

def grep(root: Path, pattern: str, targets: list[str] | None, where: str, language: str | None, ignore_case: bool, top: int) -> dict:
    """A bounded search that knows code from comments and strings, using Python's expressions so `\\b` and `\\w` mean what they look like."""
    compiled = re.compile(pattern, re.I if ignore_case else 0)
    views = Views(root)
    rows = []
    for path in selected_files(root, targets):
        if language and language_at(root, path) != language:
            continue
        text = filesystem.read_text(root / path)
        if text is None or not compiled.search(text):
            continue
        for number, line in enumerate(text.split("\n"), start=1):
            for match in compiled.finditer(line):
                kind = views.kind_at(path, number, match.start())
                if where == "any" or kind == where or (kind == "text" and where == "code"):
                    rows.append({"where": f"{path}:{number}", "path": path, "kind": kind, "text": safe_line(line)})
                    break
    per_file = Counter(row["path"] for row in rows)
    return {"pattern": pattern, "total": len(rows), "files": len(per_file), "top_files": per_file.most_common(10), "rows": rows[:top], "in": where}


def render_grep(data: dict) -> str:
    out = [f"{data['total']:,} matching lines in {data['files']:,} files" + (f", in {data['in']} only." if data["in"] != "any" else ".")]
    if data["files"] > 1:
        out += ["Most in:"] + [f"  {count:>6}  {path}" for path, count in data["top_files"][:5]]
    out += [f"{row['where']}  [{row['kind']}]  {row['text']}" for row in data["rows"]]
    out += more(data["total"] - len(data["rows"]))
    return "\n".join(out)


# ---------------------------------------------------------------- functions

def functions(root: Path, targets: list[str] | None, sort: str, include_tests: bool, top: int) -> dict:
    """The biggest and most tangled functions, by what the scanner already read. The cache makes this cheap after any scan."""
    files = [path for path in selected_files(root, targets) if include_tests or not is_test_path(path)]
    try:
        cache = Cache(filesystem.state_dir(root))
    except OSError:
        cache = Cache(None)
    records = _analyze_all(root, files, cache, None, light=True)
    cache.close()
    rows = []
    for path, record in records.items():
        for item in (record.get("facts") or {}).get("defs", []):
            length = item.get("length") or ((item.get("end") or item["line"]) - item["line"] + 1)
            label = f"{item['class']}.{item['name']}" if item.get("class") else item["name"]
            rows.append({"where": f"{path}:{item['line']}", "name": label, "lines": length, "complexity": item.get("complexity"), "params": item.get("params")})
    keyed = {"lines": lambda row: -row["lines"], "complexity": lambda row: -(row["complexity"] or 0), "params": lambda row: -(row["params"] or 0)}
    rows.sort(key=lambda row: (keyed[sort](row), row["where"]))
    total_lines = sum(row["lines"] for row in rows)
    return {"sort": sort, "total": len(rows), "lines_in_functions": total_lines, "rows": rows[:top], "over_100_lines": sum(row["lines"] > 100 for row in rows),
            "over_complexity_15": sum((row["complexity"] or 0) >= 15 for row in rows), "unparsed": sum(1 for r in records.values() if r.get("parse_error"))}


def render_functions(data: dict) -> str:
    if not data["total"]:
        return "No functions found. Functions are read for Python and the braced languages."
    out = [f"{data['total']:,} functions. {data['over_100_lines']:,} over 100 lines and {data['over_complexity_15']:,} at complexity 15 or more. Sorted by {data['sort']}.",
           "Complexity counts branches, boolean operators and comprehensions in Python, so it reads above mccabe, and branch keywords in braced languages, so it's approximate."]
    if data["unparsed"]:
        out.append(f"{data['unparsed']} files didn't parse, so their functions are missing.")
    out += [f"{row['lines']:>6} lines  complexity {row['complexity'] if row['complexity'] is not None else '?':>3}  {row['where']}  {row['name']}" for row in data["rows"]]
    out += more(data["total"] - len(data["rows"]))
    return "\n".join(out)


# ---------------------------------------------------------------- public surface

_PUBLIC = {
    "javascript": re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:declare\s+)?(?:abstract\s+)?(function\*?|class|const|let|var|type|interface|enum)\s+(\w+)([^\n{=]*)", re.M),
    "go": re.compile(r"^(func)\s+(?:\([^)]*\)\s*)?([A-Z]\w*)([^\n{]*)|^(type)\s+([A-Z]\w*)([^\n{]*)", re.M),
    "rust": re.compile(r"^[ \t]*pub\s+(?:async\s+)?(?:unsafe\s+)?(fn|struct|enum|trait|type|const|mod)\s+(\w+)([^\n{;]*)", re.M),
    "java": re.compile(r"^[ \t]*public\s+(?:(?:static|final|abstract|synchronized|sealed)\s+)*(class|interface|enum|record|[\w<>\[\],. ]+?)\s+(\w+)\s*(\([^)\n]*\)|[^\n{]*)", re.M),
}
_PUBLIC["typescript"] = _PUBLIC["javascript"]
_PUBLIC["kotlin"] = re.compile(r"^(?:public\s+)?(?:(?:data|sealed|abstract|open|suspend)\s+)*(fun|class|interface|object|val|var)\s+(\w+)([^\n{=]*)", re.M)
_PUBLIC["csharp"] = _PUBLIC["java"]


def _private_module(path: str) -> bool:
    return is_test_path(path) or is_script_path(path) or any(part.startswith("_") and part != "__init__.py" and part != "__main__.py" for part in path.split("/"))


def _python_public(text: str) -> dict[str, dict]:
    """Public names with their parameters. __all__ decides when it's a plain list, and otherwise the leading underscore does."""
    tree = ast.parse(text)
    exported = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            try:
                exported = set(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                exported = None
    surface: dict[str, dict] = {}

    def public(name: str) -> bool:
        return name in exported if exported is not None else not name.startswith("_")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(node.name):
            surface[node.name] = _python_entry(node)
        elif isinstance(node, ast.ClassDef) and public(node.name):
            surface[node.name] = {"kind": "class", "line": node.lineno, "signature": ""}
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not inner.name.startswith("_") or inner.name in ("__init__", "__call__")):
                    surface[f"{node.name}.{inner.name}"] = _python_entry(inner, method=True)
    return surface


def _python_entry(node: ast.AST, method: bool = False) -> dict:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    if method and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    defaults_from = len(positional) - len(args.defaults)
    params = [{"name": arg.arg, "required": index < defaults_from, "kind": "positional"} for index, arg in enumerate(positional)]
    params += [{"name": arg.arg, "required": default is None, "kind": "keyword"} for arg, default in zip(args.kwonlyargs, args.kw_defaults)]
    return {"kind": "function", "line": node.lineno, "signature": _signature(node), "params": params, "star": bool(args.vararg), "double_star": bool(args.kwarg)}


def _text_public(path: str, text: str, language: str) -> dict[str, dict]:
    pattern = _PUBLIC.get(language)
    if pattern is None:
        return {}
    source = load(path, text, language)
    surface = {}
    for match in pattern.finditer(source.code):
        groups = [group for group in match.groups()]
        kind, name, rest = next(((groups[i], groups[i + 1], groups[i + 2]) for i in range(0, len(groups), 3) if groups[i + 1]), (None, None, None))
        if name:
            surface[name] = {"kind": kind.strip(), "line": source.line_of(match.start()), "signature": re.sub(r"\s+", " ", rest or "").strip()[:MAX_SIGNATURE]}
    return surface


def _surface_of(path: str, text: str | None, language: str | None) -> dict[str, dict] | None:
    if text is None or not language:
        return None
    if language == "python":
        try:
            return _python_public(text)
        except (SyntaxError, ValueError, RecursionError):
            return None
    return _text_public(path, text, language)


def _breaking_reasons(old: dict, new: dict) -> list[str]:
    if "params" not in old or "params" not in new:
        return ["signature text changed"] if old.get("signature") != new.get("signature") else []
    reasons = []
    old_names = [p["name"] for p in old["params"]]
    new_by_name = {p["name"]: p for p in new["params"]}
    gone = [name for name in old_names if name not in new_by_name]
    if gone and not new["double_star"]:
        reasons.append(f"parameter removed or renamed: {', '.join(gone)}")
    added_required = [p["name"] for p in new["params"] if p["required"] and p["name"] not in old_names]
    if added_required:
        reasons.append(f"new required parameter: {', '.join(added_required)}")
    tightened = [p["name"] for p in old["params"] if not p["required"] and new_by_name.get(p["name"], {}).get("required")]
    if tightened:
        reasons.append(f"default removed: {', '.join(tightened)}")
    old_positional = [p["name"] for p in old["params"] if p["kind"] == "positional"]
    new_positional = [p["name"] for p in new["params"] if p["kind"] == "positional"]
    shared = [name for name in old_positional if name in new_positional]
    if shared != [name for name in new_positional if name in old_positional]:
        reasons.append("positional parameters reordered")
    if [p["name"] for p in new["params"] if p["kind"] == "keyword" and p["name"] in old_positional]:
        reasons.append("positional parameter became keyword-only")
    if old["star"] and not new["star"]:
        reasons.append("*args removed")
    if old["double_star"] and not new["double_star"]:
        reasons.append("**kwargs removed")
    return reasons


def api(root: Path, targets: list[str] | None, base: str | None, top: int) -> dict:
    """What callers outside a module can reach, and with a base revision, what a change did to it."""
    if base is None:
        rows = []
        modules = 0
        for path in selected_files(root, targets):
            if _private_module(path):
                continue
            language = language_at(root, path)
            surface = _surface_of(path, filesystem.read_text(root / path) if language else None, language)
            if surface:
                modules += 1
                rows += [{"where": f"{path}:{item['line']}", "name": name, "kind": item["kind"], "signature": item.get("signature", "")} for name, item in surface.items()]
        return {"base": None, "modules": modules, "total": len(rows), "rows": rows[:top]}
    changed = filesystem.changed_lines(root, base)
    if changed is None:
        raise filesystem.GitProblem("Comparing against a revision needs git")
    allowed = set(selected_files(root, targets))
    deleted, renamed = filesystem.removed_and_renamed(root, base)
    removed, signature, added = [], [], []
    candidates = [path for path in [*changed, *deleted] if (path in allowed or path in deleted) and not _private_module(path)]
    for path in dict.fromkeys(candidates):
        language = language_at(root, path)
        before = _surface_of(path, filesystem.file_at(root, base, renamed.get(path, path)), language) or {}
        after = _surface_of(path, filesystem.read_text(root / path), language) or {}
        for name, item in before.items():
            if name not in after:
                removed.append({"where": f"{path}:{item['line']}", "name": name, "kind": item["kind"]})
            else:
                reasons = _breaking_reasons(item, after[name])
                if reasons or item.get("signature") != after[name].get("signature"):
                    signature.append({"where": f"{path}:{after[name]['line']}", "name": name, "before": item.get("signature"), "after": after[name].get("signature"), "breaking": reasons})
        added += [{"where": f"{path}:{item['line']}", "name": name, "kind": item["kind"]} for name, item in after.items() if name not in before]
    return {"base": base, "files_compared": len(dict.fromkeys(candidates)), "removed": removed, "changed": signature, "added": added[:top], "added_total": len(added), "top": top}


def render_api(data: dict) -> str:
    if data["base"] is None:
        if not data["total"]:
            return "No public names found. Tests, scripts and underscore modules are left out, and names are read for Python, JS, TS, Go, Rust, Java, Kotlin and C#."
        out = [f"{data['total']:,} public names in {data['modules']:,} modules. By convention only: nothing here can see who really calls them."]
        out += [f"  {row['where']}  {row['kind']} {row['name']}{row['signature']}" for row in data["rows"]]
        return "\n".join(out + more(data["total"] - len(data["rows"])))
    breaking = [row for row in data["changed"] if row["breaking"]]
    out = [f"Against {data['base']}: {data['files_compared']} public modules changed. {len(data['removed'])} names removed, {len(breaking)} changed in a way that can break callers, "
           f"{len(data['changed']) - len(breaking)} changed otherwise, {data['added_total']} added."]
    if data["removed"]:
        out += ["", "Removed. Each breaks any caller:"] + [f"  {row['where']}  {row['kind']} {row['name']}" for row in data["removed"][:data["top"]]]
    if data["changed"]:
        out += ["", "Signatures changed:"]
        for row in data["changed"][:data["top"]]:
            out.append(f"  {row['where']}  {row['name']}  {'; '.join(row['breaking']) or 'looks compatible'}")
            out.append(f"      was {row['before']}")
            out.append(f"      now {row['after']}")
    if data["added"]:
        out += ["", "Added:"] + [f"  {row['where']}  {row['kind']} {row['name']}" for row in data["added"]]
    return "\n".join(out)


# ---------------------------------------------------------------- boundaries

# Kind, weight, whether matches inside strings count, and what it matches. Weights only rank: consequence first, then what crosses a trust boundary.
_B, _E = WORD_START, WORD_END
BOUNDARIES = (
    ("auth", 3, False, _B + r"(authenticate|authorize|authorise|login|logout|permission|permissions|require_auth|require_login|verify_token|check_password|password|csrf|oauth|jwt|api_key|apikey)" + _E),
    ("money", 3, False, _B + r"(price|prices|amount|amounts|invoice|invoices|refund|refunds|payment|payments|charge|charges|balance|balances|currency|payout|payouts|ledger|stripe|paypal|subtotal)" + _E),
    ("tenancy", 3, False, _B + r"(tenant|tenants|tenant_id|org_id|organization_id|workspace_id|account_id|customer_id)" + _E),
    ("http-in", 2, False, r"@[A-Za-z_][A-Za-z0-9_.]*\.(route|get|post|put|patch|delete|websocket|api_route)\(|(app|router|server|fastify|api)\.(get|post|put|patch|delete|use|all)\(|[^A-Za-z0-9_](HandleFunc|Handle)\(\"|@(Get|Post|Put|Delete|Patch|Request)Mapping|#\[(get|post|put|delete|patch)\(|Route::(get|post|put|patch|delete)\("),
    ("request-data", 2, False, _B + r"request\.(json|get_json|form|args|files|data|body|query_params|GET|POST|values)|req\.(body|query|params|files)|r\.(URL\.Query|FormValue|Body)|getParameter\(|@RequestBody"),
    ("database", 2, True, r"\.(execute|executemany|executescript|fetchall|fetchone|raw)\(|session\.(add|commit|delete|flush|merge)\(|(SELECT|INSERT INTO|UPDATE|DELETE FROM) |prisma\.|knex\(|gorm\.|db\.(Query|Exec|QueryRow)|sqlx::|jdbcTemplate|PreparedStatement|createQuery\("),
    ("http-out", 1, False, _B + r"(requests|httpx)\.(get|post|put|patch|delete|request|Client|AsyncClient)|aiohttp\.ClientSession|urlopen\(|axios[.(]|fetch\(|http\.(Get|Post|NewRequest)|reqwest::|HttpClient|RestTemplate|WebClient|(curl|wget) "),
    ("file-write", 1, False, r"open\([^)]*[\"'][rwax]?[wax+]b?t?[\"']|\.write_(text|bytes)\(|shutil\.(copy|copy2|copytree|move|rmtree)\(|os\.(remove|unlink|rename|replace|makedirs|rmdir)\(|fs\.(writeFile|appendFile|rm|unlink|rename)|os\.(WriteFile|Create|Remove|RemoveAll|Rename)\(|fs::(write|remove_file|remove_dir_all|rename)|Files\.(write|delete|move)\("),
    ("subprocess", 1, False, r"subprocess\.(run|call|check_call|check_output|Popen)|os\.(system|popen|exec[lv][pe]*)\(|child_process|exec\.Command|Command::new|ProcessBuilder|getRuntime\(\)\.exec"),
    ("environment", 1, False, r"os\.environ|os\.getenv|getenv\(|process\.env|std::env|System\.getenv|ENV\["),
    ("deserialize", 1, False, r"pickle\.loads?\(|yaml\.(load|unsafe_load)\(|marshal\.loads?\(|ObjectInputStream|unserialize\(|json\.loads?\(|JSON\.parse\(|json\.Unmarshal"),
    ("background", 1, False, r"@([A-Za-z_][A-Za-z0-9_.]*\.)?(task|shared_task|periodic_task)([^A-Za-z0-9_]|$)|BackgroundTasks|threading\.Thread\(|go func\(|tokio::spawn|asyncio\.create_task|ExecutorService|multiprocessing\.|setInterval\(|@Scheduled"),
    ("shared-state", 1, False, _B + r"(global [a-zA-Z_]|threading\.Lock|threading\.RLock|asyncio\.Lock|sync\.(Mutex|RWMutex)|Arc<Mutex|lru_cache|redis\.)"),
    ("crypto", 1, False, r"hashlib\.|hmac\.|bcrypt|argon2|scrypt|cryptography\.|crypto\.(createHash|createCipher|randomBytes)|Cipher\.getInstance"),
)
BOUNDARY_NAMES = tuple(row[0] for row in BOUNDARIES)


def boundaries(root: Path, targets: list[str] | None, kind: str | None, include_tests: bool, top: int) -> dict:
    """Where the code meets the outside world and what's at stake. The places these meet are what to read first, whatever a scan said about them."""
    if kind and kind not in BOUNDARY_NAMES:
        raise BadQuestion(f"No boundary kind called '{kind}'. There are: {', '.join(BOUNDARY_NAMES)}.")
    views = Views(root)
    per_file: dict[str, dict[str, int]] = defaultdict(Counter)
    sites: dict[str, list[dict]] = defaultdict(list)
    weights = {name: weight for name, weight, _, _ in BOUNDARIES}
    allowed = {name: ("code", "string") if strings_count else ("code",) for name, _, strings_count, _ in BOUNDARIES}
    wanted = [row for row in BOUNDARIES if not kind or row[0] == kind]
    rows, stopped = hits_by_file([(name, pattern, *search(root, pattern, targets)) for name, _, _, pattern in wanted])
    for hit, name, compiled in rows:
        if (is_test_path(hit.path) and not include_tests) or language_at(root, hit.path) is None:
            continue
        match = compiled.search(hit.text)
        if match and views.kind_of(hit, match) in allowed[name]:
            per_file[hit.path][name] += 1
            sites[name].append({"where": f"{hit.path}:{hit.line}", "text": safe_line(hit.text)})
    ranked = sorted(per_file.items(), key=lambda item: (-sum(weights[name] for name in item[1]), -sum(item[1].values()), item[0]))
    return {"kinds": {name: len(rows) for name, rows in sites.items()}, "kind": kind, "stopped_at_limit": stopped, "files_total": len(ranked),
            "files": [{"path": path, "score": sum(weights[name] for name in counts), "kinds": dict(counts)} for path, counts in ranked[:top]],
            "sites": {name: rows[:top] for name, rows in sites.items()} if kind else {}}


def render_boundaries(data: dict) -> str:
    if data["kind"]:
        rows = data["sites"].get(data["kind"], [])
        out = [f"{data['kind']}: {data['kinds'].get(data['kind'], 0):,} sites. Matched by name and call, so read each."]
        return "\n".join(out + [f"  {row['where']}  {row['text']}" for row in rows] + more(data["kinds"].get(data["kind"], 0) - len(rows)))
    if not data["files_total"]:
        return "No boundaries matched. The patterns cover common libraries and names, so a custom layer won't show."
    counts = ", ".join(f"{name} {count:,}" for name, count in sorted(data["kinds"].items(), key=lambda item: -item[1]))
    out = [f"An inventory, not findings. Matched by name and call, in code. Sites: {counts}.", "", f"Read these first, where the most at stake meets ({data['files_total']:,} files have at least one):"]
    out += [f"  {row['score']:>3}  {row['path']}  {', '.join(sorted(row['kinds'], key=lambda name: -row['kinds'][name]))}" for row in data["files"]]
    out += more(data["files_total"] - len(data["files"]))
    out += ["", "One kind, with its lines: `occam query boundaries --kind money`."]
    return "\n".join(out)
