"""What a file offers its callers: the names `occam query api` compares. Python from its syntax, and the others by pattern, keyed so two types' methods stay apart and overloads stay apart."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from typing import Callable

from .py_helpers import _decorator_names
from .query import MAX_LINE_READ, credential_in, go_block_names, rust_use_paths, rust_use_trees
from .source import SCRIPT_PATH, Source, is_test_path, load

MAX_SIGNATURE = 120


def _signature(node: ast.AST) -> str:
    try:
        text = ast.unparse(node.args)
    except (AttributeError, ValueError, RecursionError):
        text = "..."
    returns = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) is not None else ""
    full = f"({text}){returns}"
    if credential_in(full):  # a default value can be one
        return "(signature withheld: it looks like a credential)"
    return full if len(full) <= MAX_SIGNATURE else full[:MAX_SIGNATURE] + "..."


_PUBLIC = {
    "javascript": re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:declare\s+)?(?:abstract\s+)?(function\*?|class|const\s+enum|const|let|var|type|interface|enum|namespace)\s+(\w+)([^\n{=]*)", re.M),
    "java": re.compile(r"^[ \t]*public\s+(?:(?:static|final|abstract|synchronized|sealed)\s+)*(class|interface|enum|record|[\w<>\[\],. ]+?)\s+(\w+)\s*(\([^)\n]*\)|[^\n{]*)", re.M),
}
_PUBLIC["typescript"] = _PUBLIC["javascript"]
_PUBLIC["csharp"] = _PUBLIC["java"]
_KOTLIN_PUBLIC = re.compile(r"^[ \t]*(?:public\s+)?(?:(?:data|sealed|abstract|open|suspend|inline|tailrec|operator|infix|override|const|lateinit|enum|annotation|value|external)\s+)*(fun|class|interface|object|val|var|typealias)\s+(?:<[^>\n]*>\s*)?(?:[\w.<>?]+\.)?(\w+)([^\n{=]*)", re.M)
_JVM_SCOPE = re.compile(r"^[ \t]*(?:[\w@]+[ \t]+)*?(?:(?:class|interface|enum|record|struct|object|@interface)\s+(?P<name>\w+)|companion\s+(?P<companion>object))\b[^;{}]{0,500}\{", re.M)
_GO_FUNC = re.compile(r"^func\s+(?:\(\s*(?:\w+\s+)?\*?(?P<receiver>\w+)(?:\[[^\]\n]*\])?\s*\)\s*)?(?P<name>[A-Z]\w*)(?P<rest>[^\n{]*)", re.M)
_GO_DECLARATION = re.compile(r"^(?P<kind>type|const|var)[ \t]+(?P<names>\w+(?:[ \t]*,[ \t]*\w+)*)(?P<rest>[^\n{=]*)", re.M)
_GO_BLOCK = re.compile(r"^(?P<kind>type|const|var)[ \t]*\(", re.M)
_RUST_PUBLIC = re.compile(r"(?:^|(?<=[{;}]))[ \t]*pub\s+(?:const\s+(?=(?:unsafe\s+|async\s+|extern\s+)*fn\b))?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+(?:\"[^\"\n]*\"\s+)?)?(fn|struct|enum|trait|type|const|static|mod|union)\s+(?:mut\s+)?(\w+)([^\n{;=]*)", re.M)
_RUST_SCOPE = re.compile(r"^[ \t]*(?P<public>pub\s+)?(?:unsafe\s+)?(?:(?P<impl>impl)\b|(?P<kind>mod|trait)\s+(?P<name>\w+))", re.M)
_RUST_TRAIT_FN = re.compile(r"(?:^|(?<=[{;}]))[ \t]*(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)([^\n{;]*)", re.M)
_RUST_REEXPORT = re.compile(r"^[ \t]*pub\s+use\s+", re.M)
_RUST_MACRO = re.compile(r"#\[macro_export\][^\n]*\n(?:[ \t]*#\[[^\n]*\n)*[ \t]*macro_rules!\s+(\w+)")
_JS_EXPORT_LIST = re.compile(r"^export\s+(?:type\s+)?\{([^{}]{0,4000})\}", re.M)
_JS_EXPORT_ALL = re.compile(r"^export\s+(?:type\s+)?\*(?:\s+as\s+(\w+))?\s+from\s*['\"]", re.M)
_JS_EXPORT_DEFAULT = re.compile(r"^export\s+default\b(?!\s+(?:async\s+)?(?:abstract\s+)?(?:function\*?|class)\s+\w)", re.M)
_JS_COMMONJS_NAME = re.compile(r"^(?:module\.)?exports\.(\w+)\s*=", re.M)
_JS_COMMONJS_OBJECT = re.compile(r"^module\.exports\s*=\s*\{([^{}]{0,4000})\}", re.M)
_JS_EXPORTED_CLASS = re.compile(r"^export\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?class\s+(?P<name>\w+)[^{]{0,500}\{", re.M)
_JS_MEMBER = re.compile(r"^[ \t]+(?P<modifiers>(?:(?:public|protected|private|static|async|readonly|override|abstract|declare|get|set)\s+)*)\*?(?P<name>[A-Za-z_$][\w$]*)\??\s*(?:<[^>\n]*>\s*)?(?P<rest>\([^)\n]*\)[^\n{;=]*|:[^\n=;]*|(?==))", re.M)
_NOT_JS_MEMBERS = {"if", "for", "while", "switch", "catch", "return", "super", "else", "do", "try", "throw", "await", "yield", "new", "delete", "typeof", "void", "function"}
_RUBY_SCOPE = re.compile(r"^([ \t]*)(?:(class|module)[ \t]+([\w:]+)|class[ \t]*<<[ \t]*self\b)")
_RUBY_PUBLIC_DEF = re.compile(r"^([ \t]*)(?:(private|public|protected)[ \t]+)?def[ \t]+(self\.)?([^\s(;]+)(\([^)\n]*\))?")
_RUBY_ATTR = re.compile(r"^[ \t]*attr_(?:reader|writer|accessor)[ \t(]+(:[^\n)]*)")
_RUBY_CONSTANT = re.compile(r"^[ \t]*([A-Z]\w*)[ \t]*=(?!=)")
_RUBY_HIDES = re.compile(r"^[ \t]*(private|protected|public|private_class_method|private_constant)\b[ \t(]*(:[^\n)]*)?[ \t)]*$")
API_LANGUAGES = {"python", "javascript", "typescript", "go", "rust", "java", "kotlin", "csharp", "ruby"}
API_LIMITS = ("Python is read from syntax and the rest by pattern, so these aren't compared: Go struct fields and interface methods, Rust struct fields and items a macro makes, members of a Java or C# interface with no `public`, "
              "names behind a star export (only the export line itself is), and a value that changes without its name or type changing.")


def _private_module(path: str) -> bool:
    """Tests and underscore modules anywhere. A folder of scripts, tools or docs only at the top or just under `src/`, since inside a package `tools/` is part of it."""
    top = path[len("src/"):] if path.startswith("src/") else path
    return is_test_path(path) or bool(SCRIPT_PATH.match(top)) or any(part.startswith("_") and part != "__init__.py" and part != "__main__.py" for part in path.split("/"))


def _flat_statements(body: list) -> Iterator[ast.AST]:
    """Statements at this level, counting what's under `if` and `try` as here, since `try: from a import b` is how a module defines `b`."""
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            for field in ("body", "orelse", "finalbody"):
                yield from _flat_statements(getattr(node, field, []))
            for handler in getattr(node, "handlers", []):
                yield from _flat_statements(handler.body)


def _assigned_names(node: ast.AST) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)]


def _dunder_all(tree: ast.AST) -> tuple[set[str] | None, int | None]:
    """What `__all__` lists, and the line of one built at runtime, which can't be read here."""
    exported, computed = None, None
    for node in _flat_statements(tree.body):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and "__all__" in _assigned_names(node):
            try:
                exported = set(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                exported, computed = None, node.lineno
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__":
            try:
                exported = (exported or set()) | set(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                computed = node.lineno
    return exported, computed


def _reexported(node: ast.ImportFrom, alias: ast.alias, path: str) -> bool:
    """An import is an implementation detail unless a package's `__init__` passes on its own code, or `from a import b as b` says so. That's PEP 8's line."""
    if alias.asname and alias.asname == alias.name:
        return True
    if not path.endswith(("__init__.py", "__init__.pyi")):
        return False
    return bool(node.level) or (node.module or "").split(".")[0] in path.split("/")[:-1]


def _python_public(text: str, path: str = "") -> dict[str, dict]:
    """Public names with their parameters. __all__ decides when it's a plain list, and otherwise the leading underscore does.
    Each entry has a `shape`, which other languages' entries don't, and `@overload` declarations are kept beside the definition."""
    tree = ast.parse(text)
    exported, computed = _dunder_all(tree)
    surface: dict[str, dict] = {}
    declared: dict[str, list[dict]] = {}

    def public(name: str) -> bool:
        return name in exported if exported is not None else not name.startswith("_")

    def define(key: str, node: ast.AST, method: bool = False) -> None:
        descriptor, decorators, overload, accessor = _decorated(node, method)
        held = surface.get(key)
        if accessor and held and held.get("descriptor") == "property":
            held["accessors"] = sorted({*held["accessors"], accessor})
            return
        entry = {**_python_entry(node, method, descriptor), "decorators": decorators, **({"accessors": []} if descriptor == "property" else {})}
        if overload:
            declared.setdefault(key, []).append(entry)
            surface.setdefault(key, entry)  # holds the place for the definition that follows, if one does
        else:
            surface[key] = entry

    for node in _flat_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(node.name):
            define(node.name, node)
        elif isinstance(node, ast.ClassDef) and public(node.name):
            surface[node.name] = {"kind": "class", "line": node.lineno, "signature": "", "shape": "class", "bases": _bases(node), "decorators": _decorated(node, False)[1]}
            for inner in _flat_statements(node.body):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not inner.name.startswith("_") or inner.name in ("__init__", "__call__")):
                    define(f"{node.name}.{inner.name}", inner, method=True)
                elif isinstance(inner, (ast.Assign, ast.AnnAssign)):
                    surface.update({f"{node.name}.{name}": {"kind": "attribute", "line": inner.lineno, "signature": "", "shape": _value_shape(inner)} for name in _assigned_names(inner) if not name.startswith("_")})
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            surface.update({name: {"kind": "variable", "line": node.lineno, "signature": "", "shape": _value_shape(node)} for name in _assigned_names(node) if name != "__all__" and public(name) and name not in surface})
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                if name == "*":
                    surface[f"* from {'.' * node.level}{node.module or ''}"] = {"kind": "re-export", "line": node.lineno, "signature": "", "shape": None}
                elif name not in surface and (name in exported if exported is not None else not name.startswith("_") and _reexported(node, alias, path)):
                    surface[name] = {"kind": "re-export", "line": node.lineno, "signature": "", "shape": None}
    for key, forms in declared.items():
        head = surface.get(key)
        if head is forms[0]:
            head["overloads"] = forms[1:]
        elif head is not None and head.get("shape") == "function":
            head["overloads"] = forms
    for name in sorted(exported or ()):  # `__all__` can name what's made some other way, and dropping it from the list still breaks `import *`
        surface.setdefault(name, {"kind": "name", "line": 1, "signature": "", "shape": None})
    if computed is not None:
        surface["__all__"] = {"kind": "computed", "line": computed, "signature": ""}
    return surface


_DESCRIPTORS = {"staticmethod": "static method", "classmethod": "class method", "property": "property", "cached_property": "cached property"}
_TYPING_ONLY = {"override", "final", "deprecated"}  # they change nothing about how it's called
# Decorators whose arguments change how the result is built: @dataclass(frozen=True) makes assignment fail, kw_only changes the constructor.
_ARGUMENTS_COUNT = {"dataclass", "define", "frozen", "attrs", "dataclass_transform"}
_VALUES = (ast.Constant, ast.JoinedStr, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _decorated(node: ast.AST, method: bool) -> tuple[str | None, list[str], bool, str | None]:
    """What a definition's decorators make of it: the descriptor a method is, the other decorators by name, whether it's an `@overload`, and which accessor of a property it is."""
    descriptor, others, overload, accessor = "method" if method else None, [], False, None
    for decorator, name in zip(node.decorator_list, _decorator_names(node)):
        last = name.rsplit(".", 1)[-1]
        if method and last in _DESCRIPTORS:
            descriptor = _DESCRIPTORS[last]
        elif last == "overload":
            overload = True
        elif method and name in (f"{node.name}.setter", f"{node.name}.deleter", f"{node.name}.getter"):
            accessor = last
        elif last not in _TYPING_ONLY:  # by its own name, so `@cache` and `@functools.cache` read alike
            counts = last in _ARGUMENTS_COUNT or name in ("attr.s", "attr.attrs", "attr.define", "attr.frozen", "attrs.define", "attrs.frozen")
            arguments = _arguments(decorator) if isinstance(decorator, ast.Call) and counts else ""
            others.append((last or _source_of(decorator) or "?") + arguments)
    return descriptor, sorted(others), overload, accessor


def _arguments(call: ast.Call) -> str:
    """A decorator's arguments in one spelling: keywords in name order, and none at all the same as `()`."""
    given = [_source_of(arg) or "?" for arg in call.args] + sorted(f"{keyword.arg}={_source_of(keyword.value)}" for keyword in call.keywords)
    return f"({', '.join(given)})" if given else ""


def _bases(node: ast.ClassDef) -> str:
    listed = [_source_of(item) or "?" for item in [*node.bases, *node.keywords]]
    return f"({', '.join(listed)})" if listed else ""


def _value_shape(node: ast.AST) -> str | None:
    """`value` for what can't be called, `function` for a lambda, and None for a name or a call, which could be either."""
    value = node.value
    if isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant):
        value = value.operand
    return "value" if isinstance(value, _VALUES) else "function" if isinstance(value, ast.Lambda) else None


def _yields(node: ast.AST) -> bool:
    """A `yield` of its own, not one in a function or class defined inside it."""
    stack = list(node.body)
    while stack:
        item = stack.pop()
        if isinstance(item, (ast.Yield, ast.YieldFrom)):
            return True
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(item))
    return False


def _whole_signature(node: ast.AST) -> str:
    """Uncut, since what shows is shortened and a new parameter past that point would otherwise look like no change."""
    try:
        return f"({ast.unparse(node.args)})" + (f" -> {ast.unparse(node.returns)}" if node.returns else "")
    except (AttributeError, ValueError, RecursionError):
        return ""


def _source_of(node: ast.AST | None) -> str | None:
    try:
        return ast.unparse(node) if node is not None else None
    except (AttributeError, ValueError, RecursionError):
        return None


def _python_entry(node: ast.AST, method: bool = False, descriptor: str | None = None) -> dict:
    args = node.args
    positional = [(arg, "positional-only") for arg in args.posonlyargs] + [(arg, "positional") for arg in args.args]
    slots = list(zip(positional, [None] * (len(positional) - len(args.defaults)) + list(args.defaults)))
    if method and descriptor != "static method" and slots and slots[0][0][0].arg in ("self", "cls"):
        slots = slots[1:]
    params = [{"name": arg.arg, "required": default is None, "kind": kind, "default": _source_of(default)} for (arg, kind), default in slots]
    params += [{"name": arg.arg, "required": default is None, "kind": "keyword", "default": _source_of(default)} for arg, default in zip(args.kwonlyargs, args.kw_defaults)]
    return {"kind": "function", "line": node.lineno, "signature": _signature(node), "whole_signature": _whole_signature(node), "params": params, "star": bool(args.vararg),
            "double_star": bool(args.kwarg), "shape": "function", "descriptor": descriptor, "async": isinstance(node, ast.AsyncFunctionDef), "generator": _yields(node)}


def _keep(surface: dict[str, dict], name: str, kind: str, line: int, rest: str = "") -> None:
    """One more public name. The same name again is an overload, kept beside the first so that losing one of them shows."""
    whole = re.sub(r"\s+", " ", rest or "").strip()
    entry = {"kind": kind.strip(), "line": line, "signature": whole[:MAX_SIGNATURE], "whole_signature": whole}
    if name in surface:
        surface[name].setdefault("overloads", []).append(entry)
    else:
        surface[name] = entry


class _Scopes:
    """Which named blocks an offset sits in. One pass over the braces, so an unbalanced file can't make this quadratic. Offsets must be asked in order."""

    def __init__(self, code: str, named: dict[int, tuple[str, str]]) -> None:
        """`named` is the offset of each opening brace with a name: (name, kind)."""
        spans, stack = [], []
        for brace in re.finditer(r"[{}]", code):
            if brace.group() == "{":
                stack.append((brace.start(), named.get(brace.start())))
            elif stack:
                start, name = stack.pop()
                spans.append((start, brace.end(), name))
        spans += [(start, len(code), name) for start, name in stack]
        spans.sort()
        self._spans, self._next, self._open = spans, 0, []

    def at(self, offset: int) -> list[tuple[str, str] | None]:
        """Each block around the offset, outermost first: (name, kind), or None for one with no name, such as a function's body."""
        while self._next < len(self._spans) and self._spans[self._next][0] < offset:
            span = self._spans[self._next]
            self._next += 1
            while self._open and self._open[-1][1] <= span[0]:
                self._open.pop()
            self._open.append(span)
        while self._open and self._open[-1][1] <= offset:
            self._open.pop()
        return [span[2] for span in self._open]


def _scoped(chain: list[tuple[str, str] | None], name: str, joiner: str = ".") -> str | None:
    """The full name of a member, or None when it's inside a function's body, where it's a local."""
    if chain and chain[-1] is None:
        return None
    return joiner.join([*(link[0] for link in chain if link), name])


def _go_public(source: Source) -> dict[str, dict]:
    surface: dict[str, dict] = {}
    code = source.code
    for match in _GO_FUNC.finditer(code):
        name = f"{match.group('receiver')}.{match.group('name')}" if match.group("receiver") else match.group("name")
        _keep(surface, name, "method" if match.group("receiver") else "func", source.line_of(match.start()), match.group("rest"))
    for match in _GO_DECLARATION.finditer(code):
        for name in match.group("names").split(","):
            if name.strip()[:1].isupper():
                _keep(surface, name.strip(), match.group("kind"), source.line_of(match.start()), match.group("rest"))
    finished = 0
    for match in _GO_BLOCK.finditer(code):
        if match.start() >= finished:
            names, finished = go_block_names(code, code.find("\n", match.end()) + 1 or len(code))
            for name, offset, rest in names:
                if name[:1].isupper():
                    _keep(surface, name, match.group("kind"), source.line_of(offset), rest)
    return surface


def _rust_type(head: str) -> str:
    """The type an `impl` head is for: `<T> Trait for a::B<T> where ...` is B."""
    depth = 0
    for index, character in enumerate(head):
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
        elif depth == 0 and not character.isspace():
            head = head[index:]
            break
    named = re.split(r"\bfor\b", re.split(r"\bwhere\b", head)[0])[-1]
    return re.sub(r"<.*", "", named, flags=re.S).strip(" &*\n\t").replace("mut ", "").rsplit("::", 1)[-1]


def _rust_scopes(code: str) -> dict[int, tuple[str, str]]:
    """Each `impl`, `mod` and `trait` by its opening brace. By `find`, since an expression trying this at every head of a file with no braces would take minutes."""
    named = {}
    for match in _RUST_SCOPE.finditer(code):
        brace = code.find("{", match.end(), match.end() + 500)
        if brace >= 0 and code.find(";", match.end(), brace) < 0:
            if match.group("impl"):
                named[brace] = _rust_type(code[match.end():brace]), "impl"
            else:
                named[brace] = match.group("name"), "pub trait" if match.group("kind") == "trait" and match.group("public") else match.group("kind")
    return named


def _rust_public(source: Source) -> dict[str, dict]:
    surface: dict[str, dict] = {}
    code = source.code
    found = sorted([(match.start(), "pub", match) for match in _RUST_PUBLIC.finditer(code)] + [(match.start(), "fn", match) for match in _RUST_TRAIT_FN.finditer(code)], key=lambda row: row[0])
    scopes = _Scopes(code, _rust_scopes(code))
    for offset, what, match in found:
        chain = scopes.at(offset)
        if what == "fn" and not (chain and chain[-1] and chain[-1][1] == "pub trait"):
            continue  # a trait's methods are as public as the trait, and nothing else's are without `pub`
        kind, name, rest = ("fn", match.group(1), match.group(2)) if what == "fn" else match.groups()
        full = _scoped(chain, name, "::")
        if full:
            _keep(surface, full, kind, source.line_of(offset), rest)
    for offset, tree in rust_use_trees(code, _RUST_REEXPORT):
        for parts, visible in rust_use_paths(tree):
            _keep(surface, "* from " + "::".join(parts) if visible == "*" else visible, "pub use", source.line_of(offset))
    for match in _RUST_MACRO.finditer(code):
        _keep(surface, f"{match.group(1)}!", "macro", source.line_of(match.start()))
    return surface


def _js_names(listed: str) -> list[str]:
    """What `a, b as c, type d, x as default` exports under."""
    names = []
    for part in listed.split(","):
        words = part.replace("type ", " ", 1).split() if part.lstrip().startswith("type ") else part.split()
        if words:
            names.append(words[-1])
    return names


def _js_public(source: Source) -> dict[str, dict]:
    surface: dict[str, dict] = {}
    code, text = source.code, source.text
    for match in _PUBLIC["javascript"].finditer(code):
        _keep(surface, match.group(2), match.group(1), source.line_of(match.start()), match.group(3))
    for match in _JS_EXPORT_LIST.finditer(code):
        for name in _js_names(match.group(1)):
            _keep(surface, name, "export", source.line_of(match.start()))
    for match in _JS_EXPORT_ALL.finditer(code):
        module = text[match.end():match.end() + 500].split(text[match.end() - 1], 1)[0]
        _keep(surface, match.group(1) or f"* from {module}", "export", source.line_of(match.start()))
    for match in _JS_EXPORT_DEFAULT.finditer(code):
        _keep(surface, "default", "export", source.line_of(match.start()))
    for match in _JS_COMMONJS_NAME.finditer(code):
        _keep(surface, match.group(1), "export", source.line_of(match.start()))
    for match in _JS_COMMONJS_OBJECT.finditer(code):
        for part in match.group(1).split(","):
            name = re.match(r"\s*([A-Za-z_$][\w$]*)", part)
            if name:
                _keep(surface, name.group(1), "export", source.line_of(match.start()))
    scopes = _Scopes(code, {match.end() - 1: (match.group("name"), "class") for match in _JS_EXPORTED_CLASS.finditer(code)})
    for match in _JS_MEMBER.finditer(code):
        chain = scopes.at(match.start())
        if not chain or not chain[-1] or len(chain) != 1 or match.group("name") in _NOT_JS_MEMBERS or "private" in match.group("modifiers"):
            continue
        rest = match.group("rest")
        _keep(surface, f"{chain[-1][0]}.{match.group('name')}", "method" if rest.startswith("(") else "field", source.line_of(match.start()), rest)
    return surface


def _ruby_public(source: Source) -> dict[str, dict]:
    """By indentation, the way a formatter lays Ruby out. `Owner#m` is an instance method and `Owner.m` a class method, and `private` lasts to the end of its class."""
    surface: dict[str, dict] = {}
    scopes: list[dict] = []
    hidden: set[str] = set()

    def owner() -> str:
        return "::".join(scope["name"] for scope in scopes if scope["name"])

    for number, whole in enumerate(source.code.split("\n"), start=1):
        line = whole[:MAX_LINE_READ]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped == "end" and scopes and scopes[-1]["indent"] == indent:
            scopes.pop()
            continue
        found = _RUBY_SCOPE.match(line)
        if found and not re.search(r"[;\s]end\s*$", line):
            while scopes and scopes[-1]["indent"] >= indent:  # one that never closed can't hold what starts at its own indent
                scopes.pop()
            scopes.append({"indent": len(found.group(1)), "name": found.group(3) or "", "singleton": not found.group(3), "private": False})
            if found.group(3):
                _keep(surface, owner(), found.group(2), number)
            continue
        hides = _RUBY_HIDES.match(line)
        if hides:
            named = re.findall(r":(\w+[?!=]?)", hides.group(2) or "")
            if not named and scopes:
                scopes[-1]["private"] = hides.group(1) != "public"
            elif hides.group(1) != "public":
                hidden.update(f"{owner()}#{name}" for name in named)
                hidden.update(f"{owner()}.{name}" for name in named)
                hidden.update(f"{owner()}::{name}" for name in named)
            continue
        found = _RUBY_PUBLIC_DEF.match(line)
        if found:
            if found.group(2) in ("private", "protected") or (scopes and scopes[-1]["private"] and not found.group(3)):
                continue
            singleton = bool(found.group(3)) or bool(scopes and scopes[-1]["singleton"])
            prefix = owner()
            _keep(surface, f"{prefix}{'.' if singleton else '#'}{found.group(4)}" if prefix else found.group(4), "def", number, found.group(5) or "")
            continue
        found = _RUBY_ATTR.match(line)
        if found and not (scopes and scopes[-1]["private"]):
            for name in re.findall(r":(\w+)", found.group(1)):
                _keep(surface, f"{owner()}#{name}", "attribute", number)
            continue
        found = _RUBY_CONSTANT.match(line)
        if found:
            _keep(surface, f"{owner()}::{found.group(1)}" if owner() else found.group(1), "constant", number)
    return {name: entry for name, entry in surface.items() if name not in hidden}


def _jvm_public(source: Source, pattern: re.Pattern) -> dict[str, dict]:
    surface: dict[str, dict] = {}
    scopes = _Scopes(source.code, {match.end() - 1: ("Companion" if match.group("companion") else match.group("name"), "type") for match in _JVM_SCOPE.finditer(source.code)})
    for match in pattern.finditer(source.code):
        name = _scoped(scopes.at(match.start()), match.group(2))
        if name:
            _keep(surface, name, match.group(1), source.line_of(match.start()), match.group(3))
    return surface


_SURFACES: dict[str, Callable[[Source], dict[str, dict]]] = {
    "javascript": _js_public, "typescript": _js_public, "go": _go_public, "rust": _rust_public, "ruby": _ruby_public,
    "java": lambda source: _jvm_public(source, _PUBLIC["java"]), "csharp": lambda source: _jvm_public(source, _PUBLIC["csharp"]), "kotlin": lambda source: _jvm_public(source, _KOTLIN_PUBLIC),
}


def _text_public(path: str, text: str, language: str) -> dict[str, dict]:
    reader = _SURFACES.get(language)
    return reader(load(path, text, language)) if reader else {}


def _surface_of(path: str, text: str | None, language: str | None) -> dict[str, dict] | None:
    if text is None or not language:
        return None
    if language == "python":
        try:
            return _python_public(text, path)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return None
    return _text_public(path, text, language)
