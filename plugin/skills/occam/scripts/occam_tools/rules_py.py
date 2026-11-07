"""Python rules built on the AST. No project code is imported or run.

This module walks a file and owns what is known about it. `rules_py_defs` judges definitions and `rules_py_flow` judges statements and calls.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable

from . import rules_py_defs as defs, rules_py_flow as flow
from .py_helpers import (
    COMPREHENSIONS,
    DYNAMIC_NAMESPACE, FUNCTION_NODES, Found, HTTP_MODULES, HTTP_VERBS, KNOWN_NAMES, LOOP_NODES, Binding,
    _call_name, _dotted, _last, _names_in, _walk_own, comprehension_scopes, is_public_route, scope_bindings,
)


_IDENTIFIER_TEXT = re.compile(r"^[A-Za-z_]\w*$")


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    is_type_of = isinstance(call.func, ast.Call) and isinstance(call.func.func, ast.Name) and call.func.func.id == "type"
    return "__class__" if is_type_of else None  # `type(self)(...)` is another way to spell `self.__class__(...)`


def _is_computed_getattr(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant)


def _calls_something_unknown(tree: ast.Module, calls: list[ast.Call], called_names: dict) -> bool:
    """`eval`, `exec`, or calling what a computed `getattr` returned, directly or through a name. Only reading an attribute that way hides no call."""
    if any(isinstance(call.func, ast.Name) and call.func.id in ("eval", "exec") or _is_computed_getattr(call.func) for call in calls):
        return True
    assigned = (node for node in ast.walk(tree) if isinstance(node, ast.Assign) and _is_computed_getattr(node.value))
    return any(isinstance(target, ast.Name) and target.id in called_names for node in assigned for target in node.targets)


def _note_call(shapes: dict[str, list], call: ast.Call) -> None:
    name = _called_name(call)
    if name:
        shape = shapes.setdefault(name, [0, 0, set(), False])
        shape[0] += 1
        shape[1] = max(shape[1], sum(not isinstance(arg, ast.Starred) for arg in call.args))
        shape[2].update(keyword.arg for keyword in call.keywords if keyword.arg)
        shape[3] = shape[3] or any(isinstance(arg, ast.Starred) for arg in call.args) or any(keyword.arg is None for keyword in call.keywords)


_RETRY_NAME = re.compile(r"attempt|retr(?:y|ies)|tries|tentativa|intento", re.I)


def _runs_a_few_times(loop: ast.AST) -> bool:
    """`for table in ("a", "b"):` or `for attempt in range(3):` isn't per item, whatever its body does."""
    if not isinstance(loop, ast.For):
        return False
    if isinstance(loop.iter, (ast.Tuple, ast.List, ast.Set)):
        return len(loop.iter.elts) <= 16 and not any(isinstance(item, ast.Starred) for item in loop.iter.elts)
    if not (isinstance(loop.iter, ast.Call) and isinstance(loop.iter.func, ast.Name) and loop.iter.func.id == "range"):
        return False
    named_for_retries = isinstance(loop.target, ast.Name) and bool(_RETRY_NAME.search(loop.target.id))
    return named_for_retries or all((isinstance(arg, ast.Constant) and isinstance(arg.value, int) and arg.value <= 16)
                                    or (isinstance(arg, ast.Name) and (arg.id.isupper() or bool(_RETRY_NAME.search(arg.id)))) for arg in loop.iter.args)


class Analyzer:
    """One walk over one module. Produces findings, plus the facts that cross-file passes need."""

    def __init__(self, tree: ast.Module, text: str, path: str, code_view: str, comment_lines: set, is_test: bool, is_script: bool, notebook: bool = False):
        self.tree = tree
        self.text = text
        self.path = path
        self.code_view = code_view
        self.comment_lines = comment_lines
        self.is_test = is_test
        self.is_script = is_script
        self.notebook = notebook
        self.basename = path.rsplit("/", 1)[-1]
        self.code_strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 60}
        self.is_init = self.basename == "__init__.py"
        self.is_stub_file = path.endswith(".pyi")
        self.findings: list[Found] = []
        self.imports: list[dict] = []
        self.defs: list[dict] = []
        self.classes: list[dict] = []
        self.attr_uses: list[dict] = []
        self.checking_functions: set[str] | None = None
        self.module_aliases: dict[str, str] = {}
        self.top_names: set[str] = set()
        self.has_star = False
        self.has_getattr = False
        self.exports: set[str] = set()
        self.has_main_guard = False
        self.imported_names: dict[str, tuple[int, ast.AST, bool]] = {}
        self.routes: list[dict] = []
        self.module_mutables: dict[str, int] = {}
        self.imports_numeric = False
        self.uses_logging = False
        self.prints: list[int] = []
        self.dynamic_namespace = bool(DYNAMIC_NAMESPACE.search(code_view))
        self.function_names: set[str] = set()
        self.camel_defs: list[ast.AST] = []
        self.async_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
        self._bindings: dict[int, dict[str, list[Binding]]] = {}
        self._comprehensions: tuple[int, dict] = (0, {})
        self._global_names: set[str] | None = None
        self._value_names: set[str] | None = None
        self.name_verdicts: dict[tuple, bool] = {}

    def bindings(self, scope: ast.AST | None) -> dict[str, list[Binding]]:
        """Kept per scope, since a file with thousands of queries mustn't walk its tree for each one."""
        scope = self.tree if scope is None else scope
        if id(scope) not in self._bindings:
            self._bindings[id(scope)] = scope_bindings(scope)
        return self._bindings[id(scope)]

    def comprehensions_in(self, statement: ast.AST) -> dict:
        if self._comprehensions[0] != id(statement):
            self._comprehensions = (id(statement), comprehension_scopes(statement))
        return self._comprehensions[1]

    def declared_global(self) -> set[str]:
        if self._global_names is None:
            self._global_names = {name for node in ast.walk(self.tree) if isinstance(node, ast.Global) for name in node.names}
        return self._global_names

    def referenced_as_values(self) -> set[str]:
        """Names used other than by calling them, so that something else may be what calls them."""
        if self._value_names is None:
            called = {id(node.func) for node in ast.walk(self.tree) if isinstance(node, ast.Call)}
            self._value_names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(self.tree)
                                 if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load) and id(node) not in called}
        return self._value_names

    def add(self, rule: str, node_or_line, message: str | None = None, **overrides) -> None:
        line = node_or_line if isinstance(node_or_line, int) else getattr(node_or_line, "lineno", 1)
        self.findings.append((rule, line, message, overrides))

    def run(self) -> dict:
        self._module_level()
        self.function_names = {n.name for n in ast.walk(self.tree) if isinstance(n, FUNCTION_NODES)}
        self._walk(self.tree.body, loops=0, function=None, class_node=None)
        self._whole_file_rules()
        rebound = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)} | {n.arg for n in ast.walk(self.tree) if isinstance(n, ast.arg)}
        uses = [use for use in self.attr_uses if use["head"] not in rebound]
        return {
            "settings": defs.setting_names(self), "imports": self.imports, "defs": self.defs, "classes": self.classes, "attr_uses": uses,
            "top_names": sorted(self.top_names), "has_star": self.has_star, "has_getattr": self.has_getattr or self.dynamic_namespace,
            "exports": sorted(self.exports), "has_main_guard": self.has_main_guard, **self._call_facts(),
        }

    def _call_facts(self) -> dict:
        """How callers use each name: `calls` as [count, most positional arguments, keywords, any * or **], and `value_uses` for names passed around instead of called, whose calls can't all be seen."""
        shapes: dict[str, list] = {}
        calls = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)]
        for call in calls:
            _note_call(shapes, call)
        values = set(self.referenced_as_values())
        values.update(alias.name for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom) for alias in node.names if alias.asname)  # called under another name
        values.update(text for text in self.code_strings if _IDENTIFIER_TEXT.match(text))  # `getattr(m, 'fetch')`, or a registry keyed by name
        return {"calls": {name: [count, positional, sorted(keywords), star] for name, (count, positional, keywords, star) in shapes.items()}, "value_uses": sorted(values), "dynamic_lookup": _calls_something_unknown(self.tree, calls, shapes)}

    def _module_level(self) -> None:
        for statement in self.tree.body:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._import(statement, optional=False)
            elif isinstance(statement, ast.Try):
                self._imports_in_try(statement)
            elif isinstance(statement, ast.If):
                self._imports_in_if(statement)
            elif isinstance(statement, FUNCTION_NODES + (ast.ClassDef,)):
                self.top_names.add(statement.name)
                self.has_getattr = self.has_getattr or statement.name == "__getattr__"
            elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                self._module_assignment(statement)
            elif type(statement).__name__ == "TypeAlias":
                self.top_names.add(statement.name.id)
            if isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign)) and not self.is_script and not self.is_test:
                self._import_time_io(statement)
        self._names_in_module_blocks(self.tree.body)

    def _names_in_module_blocks(self, statements: list) -> None:
        """Names bound under a module-level if, try, with or for, such as a platform-specific definition."""
        for statement in statements:
            if isinstance(statement, FUNCTION_NODES + (ast.ClassDef,)):
                self.top_names.add(statement.name)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                self.top_names.update(name for target in targets for name in _names_in(target))
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                self.top_names.update((alias.asname or alias.name).split(".")[0] for alias in statement.names)
            elif isinstance(statement, (ast.If, ast.Try, ast.With, ast.For, ast.While)) or type(statement).__name__ == "TryStar":
                if isinstance(statement, ast.For):
                    self.top_names.update(_names_in(statement.target))
                for field in ("body", "orelse", "finalbody"):
                    self._names_in_module_blocks(getattr(statement, field, []))
                for handler in getattr(statement, "handlers", []):
                    self._names_in_module_blocks(handler.body)

    def _imports_in_try(self, statement: ast.Try) -> None:
        optional = any(self._catches_import_error(handler) for handler in statement.handlers)
        for inner in statement.body + statement.orelse + [s for h in statement.handlers for s in h.body] + statement.finalbody:
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                self._import(inner, optional=optional)

    def _imports_in_if(self, statement: ast.If) -> None:
        guard = _dotted(statement.test) if not isinstance(statement.test, ast.Compare) else ""
        is_typing = guard.endswith("TYPE_CHECKING")
        for inner in statement.body + statement.orelse:
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                self._import(inner, optional=not is_typing, runtime=not is_typing)
        if isinstance(statement.test, ast.Compare) and "__name__" in _names_in(statement.test):
            self.has_main_guard = True

    def _module_assignment(self, statement: ast.AST) -> None:
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        for target in targets:
            self.top_names.update(_names_in(target))
        value = statement.value
        if not isinstance(targets[0], ast.Name):
            return
        if targets[0].id == "__all__":
            self.exports |= {e.value for e in getattr(value, "elts", []) if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        elif self._is_mutable_container(value):
            self.module_mutables[targets[0].id] = statement.lineno

    @staticmethod
    def _catches_import_error(handler: ast.ExceptHandler) -> bool:
        names = _names_in(handler.type) if handler.type else set()
        return handler.type is None or bool(names & {"ImportError", "ModuleNotFoundError", "Exception"})

    @staticmethod
    def _is_mutable_container(value: ast.AST | None) -> bool:
        if isinstance(value, (ast.List, ast.Dict, ast.Set)):
            return True
        return isinstance(value, ast.Call) and _last(_call_name(value)) in {"list", "dict", "set", "defaultdict", "Counter", "OrderedDict", "deque"}

    def _import(self, statement: ast.AST, optional: bool, runtime: bool = True, lazy: bool = False) -> None:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                self.imports.append({"module": alias.name, "names": [], "level": 0, "line": statement.lineno, "optional": optional, "runtime": runtime and not lazy, "lazy": lazy})
                bound = alias.asname or alias.name.split(".")[0]
                self.top_names.add(bound)
                self.imported_names[bound] = (statement.lineno, statement, optional)
                self.module_aliases[bound] = alias.name if alias.asname else alias.name.split(".")[0]
                self._note_import(alias.name)
        else:
            module = statement.module or ""
            names = [alias.name for alias in statement.names]
            self.imports.append({"module": module, "names": names, "level": statement.level, "line": statement.lineno, "optional": optional, "runtime": runtime and not lazy, "lazy": lazy})
            self._note_import(module)
            for alias in statement.names:
                if alias.name == "*":
                    self.has_star = True
                    if not self.is_init:
                        self.add("star-import", statement, f"from {module} import *")
                    continue
                bound = alias.asname or alias.name
                self.top_names.add(bound)
                if module != "__future__":
                    self.imported_names[bound] = (statement.lineno, statement, optional)
                    self.module_aliases[bound] = self._dotted_name(module, alias.name, statement.level)

    def _dotted_name(self, module: str, name: str, level: int) -> str:
        """What `from module import name` refers to, which may be a submodule that gets used as `name.thing`."""
        parts = [module] if module else []
        if level:
            folders = self.path.split("/")[:-1]
            parts = folders[:len(folders) - (level - 1)] + parts
        return ".".join([*parts, name])

    def _note_import(self, module: str) -> None:
        top = module.split(".")[0]
        if top in ("numpy", "pandas", "torch", "tensorflow", "jax", "scipy", "polars"):
            self.imports_numeric = True
        if top in ("logging", "structlog", "loguru"):
            self.uses_logging = True

    def _import_time_io(self, statement: ast.AST) -> None:
        for node in ast.walk(statement):
            if isinstance(node, ast.Lambda):
                return
            if isinstance(node, ast.Call):
                name = _call_name(node)
                head = name.split(".")[0]
                last = _last(name)
                if (head in HTTP_MODULES and last in HTTP_VERBS) or name in ("urllib.request.urlopen", "urlopen", "socket.create_connection") \
                        or last in ("connect", "from_pretrained") and head not in ("signal", "self") or name in ("boto3.client", "boto3.resource"):
                    self.add("import-time-io", statement, f"{name}() runs when this module is imported.")
                    return

    def _walk(self, statements: list, loops: int, function: ast.AST | None, class_node: ast.ClassDef | None) -> None:
        previous_exit = False
        for statement in statements:
            if previous_exit:
                self.add("unreachable-code", statement)
                previous_exit = False
            self._statement(statement, loops, function, class_node)
            previous_exit = isinstance(statement, (ast.Return, ast.Raise, ast.Continue, ast.Break))

    def _statement(self, node: ast.AST, loops: int, function: ast.AST | None, class_node: ast.ClassDef | None) -> None:
        if isinstance(node, FUNCTION_NODES):
            defs.check_function(self, node, class_node)
            self._walk(node.body, 0, node, None)
            return
        if isinstance(node, ast.ClassDef):
            defs.check_class(self, node)
            self._walk(node.body, 0, None, node)
            return
        if isinstance(node, ast.If) or isinstance(node, ast.While):
            flow.check_constant_condition(self, node)
        if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            flow.check_try(self, node, function)
        if isinstance(node, LOOP_NODES):
            flow.check_loop(self, node, loops, function)
        if isinstance(node, (ast.Import, ast.ImportFrom)) and function is not None:
            self._import(node, optional=False, lazy=True)
        if isinstance(node, ast.Global):
            self.add("global-statement", node, f"global {', '.join(node.names)}")
        if isinstance(node, ast.Assert) and not self.is_test and function is not None:
            flow.check_assert(self, node, function)
        if isinstance(node, ast.Raise) and not self.is_test:
            flow.check_raise(self, node)
        if isinstance(node, ast.AugAssign) and loops and isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add) and function is not None:
            flow.check_string_concat(self, node, function)
        self._expressions(node, loops, function)
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(node, field, None)
            if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                self._walk(inner, loops + (1 if isinstance(node, LOOP_NODES) and field == "body" and not _runs_a_few_times(node) else 0), function, class_node)
        for handler in getattr(node, "handlers", []):
            self._walk(handler.body, loops, function, class_node)
        for case in getattr(node, "cases", []):
            self._walk(case.body, loops, function, class_node)

    def _expressions(self, statement: ast.AST, loops: int, function: ast.AST | None) -> None:
        """Visit the expressions that belong to this statement, not to statements nested inside it."""
        for field, value in ast.iter_fields(statement):
            if field in ("body", "orelse", "finalbody", "handlers", "cases"):
                continue
            nodes = value if isinstance(value, list) else [value]
            for item in nodes:
                if not isinstance(item, ast.AST):
                    continue
                for node, in_comprehension in self._walk_expression(item):
                    if isinstance(node, ast.Call):
                        flow.check_call(self, node, statement, loops + in_comprehension, function)
                    elif isinstance(node, ast.Attribute):
                        flow.note_attribute(self, node)
                    elif isinstance(node, ast.JoinedStr):
                        flow.check_format_string(self, node)
                    elif isinstance(node, ast.Compare):
                        flow.check_compare(self, node, loops, function)

    @staticmethod
    def _walk_expression(root: ast.AST) -> Iterable[tuple[ast.AST, bool]]:
        """Each node, and whether it's inside a comprehension, which loops just as a for statement does."""
        stack = [(root, False)]
        while stack:
            node, in_comprehension = stack.pop()
            yield node, in_comprehension
            if isinstance(node, ast.Lambda):
                continue
            if isinstance(node, COMPREHENSIONS):  # its first iterable runs once, and everything else runs per item
                first = node.generators[0]
                stack.append((first.iter, in_comprehension))
                stack.extend((child, True) for child in ast.iter_child_nodes(first) if child is not first.iter)
                stack.extend((child, True) for child in ast.iter_child_nodes(node) if child is not first)
            else:
                stack.extend((child, in_comprehension) for child in ast.iter_child_nodes(node))

    def _whole_file_rules(self) -> None:
        self._route_gap()
        self._process_state()
        self._unused_imports()
        if not self.is_stub_file:
            self._undefined_names()
        self._argv()
        if len(self.camel_defs) <= 0.3 * max(len(self.defs), 1):  # a file that is camelCase throughout has its own convention
            for node in self.camel_defs:
                self.add("convention-mismatch", node, f"'{node.name}' isn't snake_case, unlike the rest of this file.")
        if self.prints and self.uses_logging and not self.is_script and not self.is_test and not self.has_main_guard:
            self.add("print-in-library", self.prints[0], f"{len(self.prints)} print calls in a module that also logs.")

    def _route_gap(self) -> None:
        routes = self.routes
        guarded = [r for r in routes if r["guarded"]]
        if len(routes) < 3 or len(guarded) / len(routes) < 0.5:
            return
        for route in routes:
            if not route["guarded"] and not is_public_route(route["name"]):
                self.add("missing-auth", route["line"], f"{route['name']} has no auth guard, though {len(guarded)} of {len(routes)} routes here do.")

    def _process_state(self) -> None:
        if not self.module_mutables or self.is_test or self.is_script:
            return
        store_like = re.compile(r"cache|session|store|queue|counter|rate|limit|job|task|user|state|db|data|bucket|seen", re.I)
        web_module = bool(self.routes)
        reported = set()
        for node in ast.walk(self.tree):
            if not isinstance(node, FUNCTION_NODES):
                continue
            for inner in _walk_own(node):
                target = None
                if isinstance(inner, ast.Assign):
                    target = next((t.value.id for t in inner.targets if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)), None)
                elif isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and isinstance(inner.func.value, ast.Name) \
                        and inner.func.attr in ("append", "add", "update", "setdefault", "pop", "extend", "insert", "remove", "appendleft"):
                    target = inner.func.value.id
                if target in self.module_mutables and target not in reported and (web_module or store_like.search(target)):
                    reported.add(target)
                    confidence = "medium" if web_module else "low"
                    self.add("process-local-state", self.module_mutables[target], f"{target} is process-local mutable state, changed in {node.name}().", confidence=confidence)

    def _unused_imports(self) -> None:
        if self.is_init or self.notebook:
            return
        code = self.code_view
        read = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)}  # the code view blanks strings, and that would hide uses inside f-strings
        for name, (line, statement, optional) in self.imported_names.items():
            if optional or name in self.exports or name in read or name.startswith("_") or line in self.comment_lines:
                continue
            uses = len(re.findall(rf"(?<![\w.]){re.escape(name)}\b", self._code_without(statement))) if name in code else 0
            if uses == 0 and not self._mentioned_in_strings(name):
                self.add("unused-import", line, f"{name} is imported and never used.")

    def _code_without(self, statement: ast.AST) -> str:
        lines = self.code_view.split("\n")
        for index in range(statement.lineno - 1, (statement.end_lineno or statement.lineno)):
            if index < len(lines):
                lines[index] = ""
        return "\n".join(lines)

    def _mentioned_in_strings(self, name: str) -> bool:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 300 and re.search(rf"\b{re.escape(name)}\b", node.value):
                return True
        return False

    def _undefined_names(self) -> None:
        if self.has_star or self.has_getattr or self.notebook or self.dynamic_namespace:
            return
        bound: set[str] = set(self.top_names) | KNOWN_NAMES
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)
            elif isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, FUNCTION_NODES + (ast.ClassDef,)):
                bound.add(node.name)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                bound.update(node.names)
            elif type(node).__name__ in ("MatchAs", "MatchStar") and getattr(node, "name", None):
                bound.add(node.name)
            elif type(node).__name__ == "MatchMapping" and getattr(node, "rest", None):
                bound.add(node.rest)
            elif type(node).__name__ in ("TypeVar", "ParamSpec", "TypeVarTuple"):
                bound.add(node.name)
        reported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound and node.id not in reported:
                reported.add(node.id)
                self.add("undefined-name", node, f"{node.id} isn't defined or imported in this file.")

    def _argv(self) -> None:
        if self.is_test:
            return
        positions = [node for node in ast.walk(self.tree) if isinstance(node, ast.Subscript) and _dotted(node.value) == "sys.argv" and isinstance(node.slice, ast.Constant)]
        flags = [node for node in ast.walk(self.tree) if isinstance(node, ast.Compare) and _compares_a_flag_with_argv(node)]
        if len({node.slice.value for node in positions}) + len(flags) >= 2:
            self.add("handrolled-argv", flags[-1] if flags else positions[0], "Command-line options parsed by hand.")


def _compares_a_flag_with_argv(compare: ast.Compare) -> bool:
    sides = [compare.left, *compare.comparators]
    return any(isinstance(side, ast.Constant) and str(side.value).startswith("--") for side in sides) and any(_dotted(node) == "sys.argv" for side in sides for node in ast.walk(side))


def analyze(text: str, path: str, code_view: str, comment_lines: set, is_test: bool, is_script: bool, notebook: bool = False) -> tuple[list, dict, str | None]:
    """Findings and facts for one module, or the parse error if it doesn't parse on this Python."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError) as error:
        return [], {}, f"{type(error).__name__}: {error}"
    analyzer = Analyzer(tree, text, path, code_view, comment_lines, is_test, is_script, notebook)
    try:
        facts = analyzer.run()
    except RecursionError as error:
        return analyzer.findings, {}, f"RecursionError: {error}"
    return analyzer.findings, facts, None
