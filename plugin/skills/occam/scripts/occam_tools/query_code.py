"""Questions about the code itself: what's in this file, where is this name used, what's biggest, what's public, what touches the outside world."""

from __future__ import annotations

import ast
import bisect
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import files as filesystem, rules_text
from .py_helpers import _complexity, _decorator_names
from .query import MAX_LINE_READ, WORD_END, WORD_START, BadQuestion, credential_in, enclosing, Hit, hits_by_file, language_at, languages_outside, left_out_hits, left_out_note, line_of, more, outside_note, relative_path, safe_line, search, selected_files, Views
from .query_surface import API_LANGUAGES, API_LIMITS, _NOT_JS_MEMBERS, _private_module, _signature, _surface_of
from .scan import Cache, _analyze_all, analyze_text
from .source import Source, is_test_path, load

# ---------------------------------------------------------------- outline

_JS_LANGUAGES = {"javascript", "typescript"}
_JS_FUNCTION_VALUE = re.compile(
    r"^[ \t]*(?:(?:export\s+)?(?:default\s+)?(?:const|let|var)\s+|(?:(?:public|protected|private|static|readonly|override|declare)\s+)*)(?P<name>[A-Za-z_$][\w$]*)\??\s*"
    r"(?:(?::[^\n]{0,200}?)?=(?![>=])|:)\s*(?:async\s+)?(?:<[^>\n]{0,200}>\s*)?"
    r"(?:function\b[\s*\w]{0,100}(?P<fparams>\([^)]{0,500}\))|(?P<params>\([^)]{0,500}\)|[A-Za-z_$][\w$]*)\s*(?::[^=\n]{0,200})?=>)", re.M)
MAX_FILES_OUTLINED = 200
_SHELL_FUNCTION = re.compile(r"^[ \t]*(?:function[ \t]+([\w:.-]+)[ \t]*(?:\(\))?|([\w:.-]+)[ \t]*\(\))[ \t\n]*\{?", re.M)
_OTHER_SYMBOLS = {
    "ruby": re.compile(r"^[ \t]*(?:(def)[ \t]+((?:self\.)?(?:[A-Za-z_]\w*[?!=]?|\[\]=?|<=>|===?|=~|!=|<<|>>|\*\*|[+\-*/%<>!~^&|]=?))|(class|module)[ \t]+([\w:]+))", re.M),
    "perl": re.compile(r"^[ \t]*(sub)[ \t]+(\w+)|^[ \t]*(package)[ \t]+([\w:]+)", re.M),
    "lua": re.compile(r"^[ \t]*(?:local[ \t]+)?(function)[ \t]+([\w.:]+)", re.M),
    "elixir": re.compile(r"^[ \t]*(defp?|defmacro)[ \t]+(\w+)|^[ \t]*(defmodule)[ \t]+([\w.]+)", re.M),
    "sql": re.compile(r"^[ \t]*CREATE[ \t]+(?:OR[ \t]+REPLACE[ \t]+)?(?:TEMP(?:ORARY)?[ \t]+)?(TABLE|VIEW|FUNCTION|PROCEDURE|INDEX|TRIGGER|TYPE)[ \t]+(?:IF[ \t]+NOT[ \t]+EXISTS[ \t]+)?([\w.\"]+)", re.M | re.I),
    "terraform": re.compile(r"^(resource|module|data|variable|output)[ \t]+\"?([\w-]+)\"?(?:[ \t]+\"([\w-]+)\")?", re.M),
}


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
    return safe_line((doc or "").strip().split("\n", 1)[0])[:100]


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
        if language in _JS_LANGUAGES:
            known = {(item["name"], item["line"]) for item in found}
            found += [{**item, "kind": "function", "depth": 0} for item in _js_function_values(source) if (item["name"], item["line"]) not in known]
    return sorted(found, key=lambda item: item["line"])


def _js_function_values(source: Source) -> list[dict]:
    """Functions held in a name: `const f = (a) => a`, a class field, an object's `f: (a) => a`. The scanner reads only the braced top-level form of these."""
    code = source.code
    found = []
    budget = 4 * len(code)  # as the scanner's own reading does, so unbalanced input can't make this quadratic
    for match in _JS_FUNCTION_VALUE.finditer(code):
        if budget <= 0:
            break
        name = match.group("name")
        if name in _NOT_JS_MEMBERS or name in ("case", "default"):
            continue
        start = match.end()
        while start < len(code) and code[start] in " \t\n":
            start += 1
        body_start = code.find("{", start, start + 300) if match.group("fparams") else start
        if body_start >= 0 and code[body_start:body_start + 1] == "{":
            end = rules_text._matching_brace(code, body_start)
            budget -= (end if end > 0 else len(code)) - start
            end = end if end > 0 else start  # never closes, so there's no telling how long it is
        else:
            end = _expression_end(code, start)
            budget -= max(end, start) - start + 1
        given = (match.group("fparams") or match.group("params") or "").strip("() \n")
        found.append({"name": name, "line": source.line_of(match.start("name")), "end": source.line_of(end), "complexity": 1 + len(rules_text._BRANCH.findall(code[start:end + 1])),
                      "params": len([part for part in rules_text._PARAM_SPLIT.split(given) if part.strip()])})
    return found


def _expression_end(code: str, start: int) -> int:
    """Where an expression body stops: the end of its line, once every bracket has closed, or a comma, a semicolon or a closer that isn't its own."""
    depth = 0
    for index in range(start, min(len(code), start + 100_000)):
        character = code[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            if depth == 0:
                return index - 1
            depth -= 1
        elif depth == 0 and character in ",;\n":
            return index - 1
    return min(len(code), start + 100_000) - 1


def _notebook_symbols(path: str, text: str) -> list[dict]:
    """A notebook's code cells, read as one program the way the scanner reads them. Lines count through the joined cells."""
    facts = analyze_text(path, text).get("facts") or {}
    found = [{"kind": "class", "name": item["name"], "line": item["line"], "depth": 0} for item in facts.get("classes", [])]
    found += [{"kind": item["kind"], "name": item["name"], "line": item["line"], "end": item.get("end"), "depth": 1 if item.get("class") else 0, "complexity": item.get("complexity")} for item in facts.get("defs", [])]
    return sorted(found, key=lambda item: item["line"])


def outline(root: Path, targets: list[str], top: int) -> dict:
    """Symbols with line ranges, so a large file can be read by the part that matters. `top` bounds the whole answer, and not each file, so a folder can't flood it."""
    results = []
    remaining = top
    for path in selected_files(root, targets):
        language = language_at(root, path)
        if not language:
            continue
        text = filesystem.read_text(root / path)
        if text is None:
            results.append({"path": path, "language": language, "lines": 0, "symbols": [], "symbols_total": 0, "parse_error": "too large or binary to read"})
            continue
        row = {"path": path, "language": language, "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0), "symbols": [], "parse_error": None}
        if language == "python":
            try:
                row["symbols"] = _python_symbols(ast.parse(text))
            except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
                row["parse_error"] = str(error)
        elif language == "notebook":
            row["symbols"] = _notebook_symbols(path, text)
        else:
            row["symbols"] = _text_symbols(path, text, language)
        row["symbols_total"] = len(row["symbols"])
        row["symbols"] = row["symbols"][:max(remaining, 0)]
        remaining -= len(row["symbols"])
        results.append(row)
    return {"files": results[:MAX_FILES_OUTLINED], "files_total": len(results), "top": top}


def render_outline(data: dict) -> str:
    if not data["files"]:
        return "No source files in those paths."
    out = []
    for row in data["files"]:
        out.append(f"{row['path']}  ({row['lines']:,} lines, {row['language']})")
        if row["parse_error"]:
            out.append(f"  doesn't parse on this Python: {row['parse_error'][:120]}")
        for symbol in row["symbols"]:
            span = f"{symbol['line']}-{symbol['end']}" if symbol.get("end") else str(symbol["line"])
            decorated = "".join(f"@{name} " for name in symbol.get("decorators") or [])
            size = f"  complexity {symbol['complexity']}" if symbol.get("complexity") and symbol["complexity"] >= 10 else ""
            doc = f"  # {symbol['doc']}" if symbol.get("doc") else ""
            out.append(f"  {span:>11}  {'  ' * symbol['depth']}{decorated}{symbol['kind']} {symbol['name']}{symbol.get('signature', '')}{size}{doc}")
        out += more(row["symbols_total"] - len(row["symbols"]))
    if data["files_total"] > len(data["files"]):
        out.append(f"... and {data['files_total'] - len(data['files']):,} more files. Name fewer paths.")
    return "\n".join(out)


# ---------------------------------------------------------------- find

_DEFINES = r"(?:def|defp|defmacro|defmodule|class|func|fn|fun|function|interface|struct|type|enum|trait|module|sub|const|let|var|val|impl|object|record|macro_rules!)"
_LONGEST_HEAD = 400  # what comes before a function's name on its line. Past this it isn't a head, and the expressions here read short pieces
_TYPED_LANGUAGES = {"c", "cpp", "java", "csharp", "dart", "objective-c"}
_C_LANGUAGES = {"c", "cpp", "objective-c"}
_NOT_TYPE_WORDS = {"return", "throw", "new", "await", "yield", "else", "case", "goto", "delete", "not", "and", "or", "typeof", "sizeof", "in", "of", "do", "assert", "co_await", "co_return", "co_yield"}
_TYPE_WORDS = re.compile(r"^\s*(?:[A-Za-z_][\w:.]*(?:<(?:[^<>()=;]|<[^<>()=;]*>)*>)?(?:\[\])*[*&]*\s+)+[*&]*$")
_QUALIFIER = re.compile(r"[\w~.:<>]*(?:::|\.)$")
_DECORATIONS = re.compile(r"@\w+(?:\([^)]*\))?\s*|\[[^\]]*\]\s*")
_AFTER_A_HEAD = re.compile(r"^(?:\s*(?:const|noexcept|override|final|throws\b[^;{]*|where\b[^;{]*|->[^;{]*))*\s*(?:\{|;|=>|:|$)")
_JS_MEMBER_WORDS = re.compile(r"^\s*(?:(?:export|default|public|private|protected|static|async|override|abstract|declare|get|set)\s+)*\*?$")
_JS_RETURN_TYPE = re.compile(r"^:[^;{}=]*(?:\{\s*$|;\s*$)")
_JS_HOLDS_FUNCTION = re.compile(r"^(?:(?::[^\n]{0,200}?)?=(?![>=])|:)\s*(?:async\s+)?(?:<[^>\n]{0,200}>\s*)?(?:function\b|(?:\([^)\n]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=\n]{0,200})?=>)")
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


def _past_parens(text: str) -> str:
    """What follows the `(...)` that text opens with, or nothing if the line ends inside it."""
    depth = 0
    for index, character in enumerate(text[:MAX_LINE_READ]):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return text[index + 1:].strip()
    return ""


def _defined_by_shape(line: str, column: int, name: str, language: str | None) -> bool:
    """`int f(int a) {`, a Java method and a TS class method name no keyword, so without this each reads as its own caller and dead code looks used.

    Each test here leans toward calling it a call, since saying a call is a definition is what would print "Nothing refers" wrongly. So `list_for_each(a, b) {`, a C macro
    with a block, needs column 0 to count, and Kotlin, Swift and Groovy aren't here at all because `f(x) { ... }` is how they call with a trailing lambda, and Groovy's `println f(x)` is a call too.
    """
    if column > _LONGEST_HEAD:
        return False
    before, after = line[:column], line[column + len(name):].lstrip()
    if language in _JS_LANGUAGES and not after.startswith("("):
        return bool(_JS_MEMBER_WORDS.match(_QUALIFIER.sub("", before)) and _JS_HOLDS_FUNCTION.match(after))
    if not after.startswith("("):
        return False
    rest = _past_parens(after)
    if language in _JS_LANGUAGES:
        if not _JS_MEMBER_WORDS.match(before):
            return False
        return rest.startswith("{") or bool(_JS_RETURN_TYPE.match(rest)) or bool(before.strip() and rest.startswith(";"))
    if language not in _TYPED_LANGUAGES:
        return False
    head = _QUALIFIER.sub("", _DECORATIONS.sub("", before))
    if head.strip():
        return bool(_TYPE_WORDS.match(head)) and not _NOT_TYPE_WORDS & set(head.split()) and bool(_AFTER_A_HEAD.match(rest))
    if language in _C_LANGUAGES:
        return not before[:1].isspace() and (rest == "" or rest.startswith("{"))
    return rest.startswith("{")


def _role_in_text(line: str, column: int, name: str, language: str | None = None) -> str:
    line = line[:MAX_LINE_READ]
    if re.search(rf"\b{_DEFINES}(?:\s*<[^>]*>)?\s+(?:\([^)]*\)\s*)?(?:[\w.<>?]+\.)?{re.escape(name)}(?![A-Za-z0-9_])", line):  # not \b, which a name ending in ? can't meet
        return "definition"
    if _defined_by_shape(line, column, name, language):
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
            except (SyntaxError, ValueError, RecursionError, MemoryError):
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
            role = role or _role_in_text(line_of(source.code, source, hit.line), column, self.name, source.language)
        else:
            role = "comment" if kind == "comment" else "string" if kind == "string" else "text"
        return {"where": f"{hit.path}:{hit.line}", "path": hit.path, "line": hit.line, "role": role, "inside": inside, "test": is_test_path(hit.path), "text": safe_line(hit.text)}


def find(root: Path, name: str, targets: list[str] | None, top: int) -> dict:
    """Where a name is defined, imported, called and mentioned. Dotted names look up the last part, and strings keep the dotted form findable."""
    last = name.rsplit(".", 1)[-1]
    if not last.strip():
        raise BadQuestion(f"'{name}' has no name in it to look for. Nothing was checked.")
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
    elsewhere: list[Hit] = []
    elsewhere_stopped = False
    if not references:
        hits_dynamic, _ = search(root, r"getattr\(|importlib|__import__|globals\(\)|reflect\.|Class\.forName", targets, limit=1)
        dynamic = bool(hits_dynamic)
        if not targets:
            elsewhere, elsewhere_stopped = left_out_hits(root, [last])
    return {"name": name, "searched": last, "total": len(hits), "files": len(per_file), "stopped_at_limit": stopped, "files_not_classified": max(0, len(per_file) - len(readable)),
            "counts": {role: len(items) for role, items in groups.items()}, "groups": {role: items[:top] for role, items in groups.items()},
            "top_files": per_file.most_common(10), "references": references, "dynamic_use_exists": dynamic, "left_out": left_out_note(root) if not references else "", "only_in": list(targets or []),
            "left_out_hits": [{"where": f"{hit.path}:{hit.line}", "text": safe_line(hit.text)} for hit in elsewhere[:top]], "left_out_hits_total": len(elsewhere), "left_out_hits_stopped": elsewhere_stopped}


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
        if data.get("only_in"):
            out.append(f"Only {', '.join(data['only_in'])} was searched.")
    if data.get("left_out_hits_total"):
        out += ["", f"But left-out files name it on {'at least ' if data['left_out_hits_stopped'] else ''}{data['left_out_hits_total']:,} lines, and those can be real callers:"]
        out += [f"  {row['where']}  {row['text']}" for row in data["left_out_hits"]] + more(data["left_out_hits_total"] - len(data["left_out_hits"]))
    if data["left_out"]:
        out.append(data["left_out"])
    return "\n".join(out)


# ---------------------------------------------------------------- grep

def _too_large(path: Path) -> int:
    try:
        return int(filesystem.is_plain_file(path) and path.stat().st_size > filesystem.MAX_FILE_BYTES)
    except OSError:
        return 0


def grep(root: Path, pattern: str, targets: list[str] | None, where: str, language: str | None, ignore_case: bool, top: int) -> dict:
    """A bounded search that knows code from comments and strings, using Python's expressions so `\\b` and `\\w` mean what they look like."""
    compiled = re.compile(pattern, re.I if ignore_case else 0)
    views = Views(root)
    rows = []
    too_large = 0
    for path in selected_files(root, targets):
        if language and language_at(root, path) != language:
            continue
        text = filesystem.read_text(root / path)
        if text is None:
            too_large += _too_large(root / path)
            continue
        if not compiled.search(text):
            continue
        for number, line in enumerate(text.split("\n"), start=1):
            for match in compiled.finditer(line):
                kind = views.kind_at(path, number, match.start())
                if where == "any" or kind == where or (kind == "text" and where == "code"):
                    rows.append({"where": f"{path}:{number}", "path": path, "kind": kind, "text": safe_line(line)})
                    break
    per_file = Counter(row["path"] for row in rows)
    return {"pattern": pattern, "total": len(rows), "files": len(per_file), "top_files": per_file.most_common(10), "rows": rows[:top], "in": where, "too_large": too_large, "left_out": left_out_note(root) if not rows else ""}


def render_grep(data: dict) -> str:
    out = [f"{data['total']:,} matching lines in {data['files']:,} files" + (f", in {data['in']} only." if data["in"] != "any" else ".")]
    if data["files"] > 1:
        out += ["Most in:"] + [f"  {count:>6}  {path}" for path, count in data["top_files"][:5]]
    out += [f"{row['where']}  [{row['kind']}]  {row['text']}" for row in data["rows"]]
    out += more(data["total"] - len(data["rows"]))
    if data["too_large"]:
        out.append(f"{data['too_large']:,} files over {filesystem.MAX_FILE_BYTES // 1_000_000} MB weren't searched. `occam.sh grep` reads them.")
    if data["left_out"]:
        out.append(data["left_out"])
    return "\n".join(out)


# ---------------------------------------------------------------- functions

_RUBY_DEF = re.compile(r"^([ \t]*)(?:(?:private|public|protected)[ \t]+)?def[ \t]+((?:self\.)?[^\s(;]+)(\([^)\n]*\))?")
_RUBY_BRANCH = re.compile(r"\b(?:if|unless|elsif|while|until|for|when|rescue)\b|&&|\|\|")
_FUNCTION_LANGUAGES = {"python", "notebook", "ruby", "shell", *rules_text.C_FAMILY}


def _ruby_methods(code: str) -> list[dict]:
    """Methods, ended by the `end` at the same indent, which is how a formatter lays them out. Counted once per line, so a file of nothing but `def` can't make this quadratic."""
    lines = code.split("\n")
    closers: dict[str, list[int]] = defaultdict(list)
    branches = [0]
    for number, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped.endswith("end") and not stripped[:-3].strip():
            closers[stripped[:-3]].append(number)
        branches.append(branches[-1] + len(_RUBY_BRANCH.findall(line[:MAX_LINE_READ])))
    found = []
    for number, line in enumerate(lines):
        match = _RUBY_DEF.match(line[:MAX_LINE_READ])
        if not match:
            continue
        ends = closers.get(match.group(1), [])
        after = bisect.bisect_right(ends, number)
        whole_line = re.search(r"[;\s]end\s*$", line[:MAX_LINE_READ]) or re.search(r"\)?\s=\s", line[match.end():MAX_LINE_READ])
        end = number if whole_line or after == len(ends) else ends[after]
        given = match.group(3)
        found.append({"name": match.group(2), "line": number + 1, "end": end + 1, "complexity": 1 + branches[end + 1] - branches[number], "params": len(given.split(",")) if given and given.strip("() ") else 0})
    return found


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
    views = Views(root)
    for path in files:
        source = views.source(path) if language_at(root, path) == "ruby" else None
        for item in _ruby_methods(source.code) if source else []:
            rows.append({"where": f"{path}:{item['line']}", "name": item["name"], "lines": item["end"] - item["line"] + 1, "complexity": item["complexity"], "params": item["params"]})
    known = {(row["where"], row["name"]) for row in rows}
    for path in _files_holding_functions(root, files, targets):
        source = views.source(path)
        for item in _js_function_values(source) if source else []:
            where = f"{path}:{item['line']}"
            if (where, item["name"]) not in known:
                rows.append({"where": where, "name": item["name"], "lines": item["end"] - item["line"] + 1, "complexity": item["complexity"], "params": item["params"]})
    keyed = {"lines": lambda row: -row["lines"], "complexity": lambda row: -(row["complexity"] or 0), "params": lambda row: -(row["params"] or 0)}
    rows.sort(key=lambda row: (keyed[sort](row), row["where"]))
    total_lines = sum(row["lines"] for row in rows)
    return {"sort": sort, "total": len(rows), "lines_in_functions": total_lines, "rows": rows[:top], "over_100_lines": sum(row["lines"] > 100 for row in rows),
            "over_complexity_15": sum((row["complexity"] or 0) >= 15 for row in rows), "unparsed": sum(1 for r in records.values() if r.get("parse_error")),
            "outside": languages_outside(root, targets, _FUNCTION_LANGUAGES)}


def _files_holding_functions(root: Path, files: list[str], targets: list[str] | None) -> list[str]:
    """JS and TS files with anything like an arrow or a function value, found by search first, since a scan's cache has already made the rest of this cheap."""
    wanted = [path for path in files if language_at(root, path) in _JS_LANGUAGES]
    if not wanted:
        return []
    allowed = set(wanted)
    hits, stopped = search(root, ["=>", "function"], targets, fixed=True, only=lambda path: path in allowed)
    return wanted if stopped else sorted({hit.path for hit in hits})


def render_functions(data: dict) -> str:
    if not data["total"]:
        return " ".join(filter(None, ["No functions found. Functions are read for Python, Ruby and the braced languages, and a function passed straight to a call has no name to list. `occam query outline` lists definitions in more.", outside_note(data.get("outside"))]))
    out = [f"{data['total']:,} functions. {data['over_100_lines']:,} over 100 lines and {data['over_complexity_15']:,} at complexity 15 or more. Sorted by {data['sort']}.",
           "Complexity counts branches, boolean operators and comprehensions in Python, so it reads above mccabe, and branch keywords in braced languages and Ruby, so it's approximate."]
    if data.get("outside"):
        out.append(outside_note(data["outside"]))
    if data["unparsed"]:
        out.append(f"{data['unparsed']} files didn't parse, so their functions are missing.")
    out += [f"{row['lines']:>6} lines  complexity {row['complexity'] if row['complexity'] is not None else '?':>3}  {row['where']}  {row['name']}" for row in data["rows"]]
    out += more(data["total"] - len(data["rows"]))
    return "\n".join(out)


# ---------------------------------------------------------------- public surface

def _gone_params(old: dict, new: dict) -> list[str]:
    kept = {p["name"] for p in new["params"]}
    gone = [p["name"] for p in old["params"] if p["name"] not in kept]
    return [f"parameter removed or renamed: {', '.join(gone)}"] if gone and not new["double_star"] else []


def _new_required(old: dict, new: dict) -> list[str]:
    before = {p["name"] for p in old["params"]}
    added = [p["name"] for p in new["params"] if p["required"] and p["name"] not in before]
    return [f"new required parameter: {', '.join(added)}"] if added else []


def _lost_defaults(old: dict, new: dict) -> list[str]:
    now = {p["name"]: p for p in new["params"]}
    lost = [p["name"] for p in old["params"] if not p["required"] and now.get(p["name"], {}).get("required")]
    return [f"default removed: {', '.join(lost)}"] if lost else []


def _positional(entry: dict) -> list[str]:
    return [p["name"] for p in entry["params"] if p["kind"] == "positional"]


def _reordered(old: dict, new: dict) -> list[str]:
    before, after = _positional(old), _positional(new)
    return ["positional parameters reordered"] if [n for n in before if n in after] != [n for n in after if n in before] else []


def _made_keyword_only(old: dict, new: dict) -> list[str]:
    before = _positional(old)
    return ["positional parameter became keyword-only"] if any(p["kind"] == "keyword" and p["name"] in before for p in new["params"]) else []


def _lost_star_args(old: dict, new: dict) -> list[str]:
    return [*(["*args removed"] if old["star"] and not new["star"] else []), *(["**kwargs removed"] if old["double_star"] and not new["double_star"] else [])]


def _breaking_reasons(old: dict, new: dict) -> list[str]:
    """What about a changed signature can break a caller. Without parsed parameters, all that can be said is that the text changed."""
    if "params" not in old or "params" not in new:
        return ["signature text changed"] if _shape(old) != _shape(new) else []
    return [reason for check in (_gone_params, _new_required, _lost_defaults, _reordered, _made_keyword_only, _lost_star_args) for reason in check(old, new)]


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
                rows += [{"where": f"{path}:{form['line']}", "name": name, "kind": form["kind"], "signature": form.get("signature", "")} for name, item in surface.items() for form in _forms(item)]
        return {"base": None, "modules": modules, "total": len(rows), "rows": rows[:top]}
    changed = filesystem.changed_lines(root, base)
    if changed is None:
        raise filesystem.GitProblem("Comparing against a revision needs git")
    allowed = set(selected_files(root, targets))
    deleted, renamed = filesystem.removed_and_renamed(root, base)
    removed, signature, added = [], [], []
    asked = [relative_path(root, target).rstrip("/") for target in targets or []]
    within = lambda path: not asked or "." in asked or any(path == folder or path.startswith(folder + "/") for folder in asked)  # noqa: E731
    named = [path for path in dict.fromkeys([*changed, *deleted]) if path in allowed or (path in deleted and within(path))]
    outside: Counter = Counter()
    unread, computed = [], []
    compared = 0
    left_as_private = sum(1 for path in named if _private_module(path) and language_at(root, path))
    for path in named:
        language = language_at(root, path)
        if not language or _private_module(path):
            continue
        if language not in API_LANGUAGES:
            outside[language] += 1
            continue
        old_text, new_text = filesystem.file_at(root, base, renamed.get(path, path)), filesystem.read_text(root / path)
        before, after = _surface_of(path, old_text, language), _surface_of(path, new_text, language)
        if (old_text is not None and before is None) or (new_text is not None and after is None) or (new_text is None and path not in deleted and (root / path).exists()):
            unread.append(path)  # all its names would otherwise read as removed or as added
            continue
        compared += 1
        before, after = before or {}, after or {}
        if [before.pop("__all__", None), after.pop("__all__", None)] != [None, None]:
            computed.append(path)
        for name, item in before.items():
            if name not in after:
                removed += _removed_rows(path, name, _forms(item))
                continue
            gone, fresh = _unmatched(_forms(item), _forms(after[name])), _unmatched(_forms(after[name]), _forms(item))
            for old, new in zip(gone, fresh):  # as many of each as can pair up changed, and what's left of one side went or came
                signature.append({"where": f"{path}:{new['line']}", "name": name, "before": _shown(old), "after": _shown(new), "breaking": _breaking_reasons(old, new)})
            removed += _removed_rows(path, name, gone[len(fresh):], overload=True)
            added += [{"where": f"{path}:{new['line']}", "name": name + (new.get("signature") or ""), "kind": new["kind"]} for new in fresh[len(gone):]]
        added += [{"where": f"{path}:{form['line']}", "name": name, "kind": form["kind"]} for name, item in after.items() if name not in before for form in _forms(item)]
    return {"base": base, "files_compared": compared, "removed": removed, "changed": signature, "added": added[:top], "added_total": len(added), "top": top,
            "outside": sorted(outside.items(), key=lambda row: (-row[1], row[0])), "unread": unread, "computed": computed, "left_as_private": left_as_private}


def _shape(entry: dict) -> str:
    return entry.get("whole_signature") or entry.get("signature") or ""


def _shown(entry: dict) -> str:
    return "(signature withheld: it looks like a credential)" if credential_in(_shape(entry)) else _shape(entry)


def _forms(entry: dict) -> list[dict]:
    """An entry and its overloads."""
    return [entry, *entry.get("overloads", [])]


def _unmatched(forms: list[dict], others: list[dict]) -> list[dict]:
    """Those of `forms` with no equal among `others`, each matched once."""
    left = Counter(_shape(form) for form in others)
    found = []
    for form in forms:
        if left[_shape(form)] > 0:
            left[_shape(form)] -= 1
        else:
            found.append(form)
    return found


def _removed_rows(path: str, name: str, forms: list[dict], overload: bool = False) -> list[dict]:
    return [{"where": f"{path}:{form['line']}", "name": name + (form.get("signature") or "" if overload or len(forms) > 1 else ""), "kind": form["kind"]} for form in forms]


def render_api(data: dict) -> str:
    if data["base"] is None:
        if not data["total"]:
            return "No public names found. Tests, scripts and underscore modules are left out, and names are read for Python, JS, TS, Go, Rust, Java, Kotlin, C# and Ruby."
        out = [f"{data['total']:,} public names in {data['modules']:,} modules. By convention only: nothing here can see who really calls them."]
        out += [f"  {row['where']}  {row['kind']} {row['name']}{row['signature']}" for row in data["rows"]]
        return "\n".join(out + more(data["total"] - len(data["rows"])))
    breaking = [row for row in data["changed"] if row["breaking"]]
    out = [f"Against {data['base']}: {data['files_compared']} public modules changed. {len(data['removed'])} names removed, {len(breaking)} changed in a way that can break callers, "
           f"{len(data['changed']) - len(breaking)} changed otherwise, {data['added_total']} added.", API_LIMITS]
    if data.get("outside"):
        out.append(outside_note(data["outside"]) + " Those changed here, and they aren't counted above.")
    if data.get("unread"):
        out.append(f"Couldn't parse or read {len(data['unread'])} changed files, so they aren't counted above: {', '.join(data['unread'][:6])}.")
    if data.get("computed"):
        out.append(f"`__all__` is built at runtime in {', '.join(data['computed'][:6])}, so those were read by the underscore convention.")
    if data.get("left_as_private"):
        out.append(f"{data['left_as_private']} changed code files are tests, scripts or underscore modules, which this doesn't read as public.")
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
_BOUNDARY_LANGUAGES = {"python", "notebook", "javascript", "typescript", "go", "java", "kotlin", "rust", "ruby", "php", "csharp", "c", "cpp", "shell"}
_BROWSER_LANGUAGES = {"javascript", "typescript"}
_NOT_PROGRAMS = {"html", "css", "markdown", "xml"}
_DECORATOR = "^[ \t]*@"  # a real tab, as git reads these. A decorator leads its line. Ruby's `@cache.delete(key)` does too and is a call, which is dropped by language
BOUNDARIES = (
    ("auth", 3, False, _B + r"(authenticate|authorize|authorise|login|logout|permission|permissions|require_auth|require_login|verify_token|check_password|password|csrf|oauth|jwt|api_key|apikey|api_token|access_token|auth_token|bearer)" + _E + r"|(API|ACCESS|AUTH)_TOKEN"),
    ("money", 3, False, _B + r"(price|prices|amount|amounts|invoice|invoices|refund|refunds|payment|payments|charge|charges|balance|balances|currency|payout|payouts|ledger|stripe|paypal|subtotal)" + _E),
    ("tenancy", 3, False, _B + r"(tenant|tenants|tenant_id|org_id|organization_id|workspace_id|account_id|customer_id)" + _E),
    ("http-in", 2, False, _DECORATOR + r"[A-Za-z_][A-Za-z0-9_.]*\.(route|get|post|put|patch|delete|websocket|api_route)\(|(app|router|server|fastify|api)\.(get|post|put|patch|delete|use|all)\(|[^A-Za-z0-9_](HandleFunc|Handle)\(\"|@(Get|Post|Put|Delete|Patch|Request)Mapping|#\[(get|post|put|delete|patch)\(|Route::(get|post|put|patch|delete)\("),
    ("request-data", 2, False, _B + r"request\.(json|get_json|form|args|files|data|body|query_params|GET|POST|values)|req\.(body|query|params|files)|r\.(URL\.Query|FormValue|Body)|getParameter\(|@RequestBody"),
    ("database", 2, True, r"\.(execute|executemany|executescript|fetchall|fetchone|raw)\(|session\.(add|commit|delete|flush|merge)\(|(SELECT|INSERT INTO|UPDATE|DELETE FROM) |prisma\.|knex\(|gorm\.|db\.(Query|Exec|QueryRow)|sqlx::|jdbcTemplate|PreparedStatement|createQuery\("),
    ("http-out", 1, False, _B + r"(requests|httpx)\.(get|post|put|patch|delete|request|Client|AsyncClient)|aiohttp\.ClientSession|urlopen\(|axios[.(]|(^|[^.A-Za-z0-9_])fetch\(|(window|globalThis)\.fetch\(|http\.(Get|Post|NewRequest)|reqwest::|HttpClient|RestTemplate|WebClient|(curl|wget) |Net::HTTP|Faraday|HTTParty|URLSession|GuzzleHttp|curl_exec\(|smtplib\.|ftplib\.|socket\.(socket|create_connection)\("),
    ("file-write", 1, False, r"open\([^)]*[\"'][rwax]?[wax+]b?t?[\"']|\.write_(text|bytes)\(|shutil\.(copy|copy2|copytree|move|rmtree)\(|os\.(remove|unlink|rename|replace|makedirs|rmdir)\(|fs\.(writeFile|appendFile|rm|unlink|rename)|os\.(WriteFile|Create|Remove|RemoveAll|Rename)\(|fs::(write|remove_file|remove_dir_all|rename)|Files\.(write|delete|move)\(|File\.(write|delete|rename|unlink)|File\.open\([^)]*[\"'][wa]|FileUtils\.|IO\.write|file_put_contents\(|fwrite\("),
    ("subprocess", 1, False, r"subprocess\.(run|call|check_call|check_output|Popen)|os\.(system|popen|exec[lv][pe]*)\(|child_process|exec\.Command|Command::new|ProcessBuilder|getRuntime\(\)\.exec|Open3\.|IO\.popen|Kernel\.(system|exec|spawn)|(^|[^.A-Za-z0-9_])(system|spawn|popen|shell_exec|passthru|proc_open)\(|Process\.Start|^[ \t]*(system|spawn|exec) +[\"'`]"),
    ("environment", 1, False, r"os\.environ|os\.getenv|getenv\(|process\.env|std::env|System\.getenv|ENV\[|ENV\.fetch|\$_ENV|GetEnvironmentVariable"),
    ("deserialize", 1, False, r"pickle\.loads?\(|yaml\.(load|unsafe_load)\(|marshal\.loads?\(|ObjectInputStream|unserialize\(|json\.loads?\(|JSON\.parse\(|json\.Unmarshal"),
    ("background", 1, False, r"@([A-Za-z_][A-Za-z0-9_.]*\.)?(task|shared_task|periodic_task)([^A-Za-z0-9_]|$)|BackgroundTasks|threading\.Thread\(|go func\(|tokio::spawn|asyncio\.create_task|ExecutorService|multiprocessing\.|setInterval\(|@Scheduled"),
    ("shared-state", 1, False, _B + r"(global [a-zA-Z_]|threading\.Lock|threading\.RLock|asyncio\.Lock|sync\.(Mutex|RWMutex)|Arc<Mutex|lru_cache|redis\.)"),
    ("crypto", 1, False, r"hashlib\.|hmac\.|bcrypt|argon2|scrypt|cryptography\.|crypto\.(createHash|createCipher|randomBytes)|Cipher\.getInstance"),
)
BOUNDARY_NAMES = tuple(row[0] for row in BOUNDARIES)


def _means_it_here(name: str, hit: Hit, match: re.Match, language: str | None) -> bool:
    """Whether a match means what its pattern does in this language."""
    if language is None or language in _NOT_PROGRAMS:
        return False
    if name == "http-out" and "fetch(" in match.group(0):  # elsewhere it's a method of a cursor or a mapping
        return language in _BROWSER_LANGUAGES
    if name == "http-in" and hit.text.lstrip().startswith("@"):  # Ruby has no decorators, so `@args.delete("version")` is a call
        return language != "ruby"
    return True


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
        if is_test_path(hit.path) and not include_tests:
            continue
        match = compiled.search(hit.text)
        if match and _means_it_here(name, hit, match, language_at(root, hit.path)) and views.kind_of(hit, match) in allowed[name]:
            per_file[hit.path][name] += 1
            sites[name].append({"where": f"{hit.path}:{hit.line}", "text": safe_line(hit.text)})
    ranked = sorted(per_file.items(), key=lambda item: (-sum(weights[name] for name in item[1]), -sum(item[1].values()), item[0]))
    return {"kinds": {name: len(rows) for name, rows in sites.items()}, "kind": kind, "stopped_at_limit": stopped, "files_total": len(ranked),
            "files": [{"path": path, "score": sum(weights[name] for name in counts), "kinds": dict(counts)} for path, counts in ranked[:top]],
            "sites": {name: rows[:top] for name, rows in sites.items()} if kind else {}, "outside": languages_outside(root, targets, _BOUNDARY_LANGUAGES)}


_UNSEEN = "The patterns cover common libraries and names, so a project's own wrapper around them won't show, and a low count isn't a low number."


def render_boundaries(data: dict) -> str:
    stopped = " A search stopped at its limit of matches, so these counts are low. Narrow it with a path." if data["stopped_at_limit"] else ""
    if data["kind"]:
        rows = data["sites"].get(data["kind"], [])
        out = [" ".join(filter(None, [f"{data['kind']}: {data['kinds'].get(data['kind'], 0):,} sites. Matched by name and call, so read each.{stopped}", _UNSEEN, outside_note(data.get("outside"))]))]
        return "\n".join(out + [f"  {row['where']}  {row['text']}" for row in rows] + more(data["kinds"].get(data["kind"], 0) - len(rows)))
    if not data["files_total"]:
        return " ".join(filter(None, ["No boundaries matched.", _UNSEEN, outside_note(data.get("outside"))]))
    counts = ", ".join(f"{name} {count:,}" for name, count in sorted(data["kinds"].items(), key=lambda item: -item[1]))
    out = [" ".join(filter(None, [f"An inventory, not findings. Matched by name and call, in code. Sites: {counts}.{stopped}", _UNSEEN, outside_note(data.get("outside"))])), "", f"Read these first, where the most at stake meets ({data['files_total']:,} files have at least one):"]
    out += [f"  {row['score']:>3}  {row['path']}  {', '.join(sorted(row['kinds'], key=lambda name: -row['kinds'][name]))}" for row in data["files"]]
    out += more(data["files_total"] - len(data["files"]))
    out += ["", "One kind, with its lines: `occam query boundaries --kind money`."]
    return "\n".join(out)
