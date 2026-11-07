"""Python rules about definitions: functions, classes, routes and tests."""

from __future__ import annotations

import ast
import re

from .py_helpers import (
    ONCE_ONLY_CALLS,
    ABSTRACT_NAME, AUTH_CALL, AUTH_DECORATOR, AUTH_DEPEND, FUNCTION_NODES, GENERIC_TEST, HEDGE_NAME, HELPERS,
    PATTERN_CLASS, ROUTE_DECORATOR, TWIN_HEDGE, VAGUE_CLASS, _body, _call_name, _complexity, _decorator_names,
    _docstring, _dotted, _has_sql, _last, _max_nesting, _names_in, _string_parts, _walk_own, looks_like_auth_check, shape_hash,
)


FILE_SINKS = {"open", "os.path.join", "send_file", "Path", "pathlib.Path", "FileResponse", "os.remove", "shutil.copy"}
REQUEST_SOURCE = re.compile(r"'(?:query|query_params|args|form|params|request|req|GET|POST|json|body)'")
CHECKING_CALL = re.compile(r"(?:assert|check|verify|expect|ensure|validate|raises|fail|should)", re.I)
ENCRYPTION_NAME = re.compile(r"(?:^|_)(?:encrypt|decrypt|cipher|obfuscate)", re.I)
COUNT_LIKE = re.compile(r"(?:count|total|num|size|len|calls?|attempts?)\w*$", re.I)
DOCSTRING_FILLER = {"the", "a", "an", "this", "function", "method", "of", "for", "to", "class"}
NO_OP_NAME = re.compile(r"_*(?:noop|nop|no_op|do_nothing)(?:_\w*)?", re.I)
NULL_OBJECT_CLASS = re.compile(r"_*(?:Null|Noop|NoOp|Nop)(?=[A-Z_]|$)")


def check_function(ctx, node: ast.AST, class_node: ast.ClassDef | None) -> None:
    name = node.name
    body = _body(node)
    decorators = _decorator_names(node)
    decorator_last = {_last(d) for d in decorators}
    length = (node.end_lineno or node.lineno) - node.lineno + 1
    complexity = _complexity(node)
    params = [arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs if arg.arg not in ("self", "cls")]
    hashed, statements = shape_hash(node)
    ctx.defs.append({"name": name, "line": node.lineno, "end": node.end_lineno, "kind": "method" if class_node else "function",
                      "class": class_node.name if class_node else None, "decorated": bool(decorators), "hash": hashed,
                      "statements": statements, "length": length, "options": _options(node), "complexity": complexity, "params": len(params)})
    if not ctx.is_stub_file:
        _stub_rules(ctx, node, body, decorator_last, class_node)
    if not ctx.is_test:
        _size_rules(ctx, node, name, length, complexity, params)
        _api_rules(ctx, node, name, body, params, decorator_last, complexity, class_node)
        _naming(ctx, node, name, class_node)
    else:
        _test_function(ctx, node, name, decorator_last)
    _defaults(ctx, node)
    if isinstance(node, ast.AsyncFunctionDef) and not decorators:
        own = list(_walk_own(node))
        if not any(isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith, ast.Yield, ast.YieldFrom)) for n in own) and body and not ctx.is_test:
            ctx.add("async-no-await", node, f"{name} is async but never awaits.")
    if decorator_last & ROUTE_DECORATOR or _is_fastapi_route(decorators):
        _route(ctx, node, decorators)
    if name in ("lru_cache", "cache"):
        return
    for decorator in node.decorator_list:
        _cache_decorator(ctx, decorator, class_node)


def _options(node) -> list:
    """Parameters with defaults, as [name, position among positional parameters or -1], without self and cls."""
    arguments = node.args
    positional = [arg for arg in arguments.posonlyargs + arguments.args if arg.arg not in ("self", "cls")]
    defaulted = positional[len(positional) - len(arguments.defaults):] if arguments.defaults else []
    options = [[arg.arg, positional.index(arg)] for arg in defaulted]
    options += [[arg.arg, -1] for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults) if default is not None]
    return [option for option in options if not option[0].startswith("_")]


def _in_abstract_class(class_node) -> bool:
    if class_node is None:
        return False
    bases = {_last(_dotted(base)) for base in class_node.bases}
    return bool(ABSTRACT_NAME.search(class_node.name) or bases & {"Protocol", "ABC", "ABCMeta"}
                or any("Protocol" in b for b in bases) or re.search(r"Error$|Exception$", class_node.name))


def _is_empty(body: list) -> bool:
    if not body:
        return True
    only = body[0]
    return len(body) == 1 and (isinstance(only, ast.Pass) or (isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis))


def _stub_rules(ctx, node, body, decorator_last, class_node) -> None:
    name = node.name
    if {"abstractmethod", "overload", "abstractproperty", "abc.abstractmethod", "override"} & decorator_last or ctx.is_test:
        return
    if _in_abstract_class(class_node) or (name.startswith("__") and name != "__init__"):
        return
    owner = {"owner": class_node.name} if class_node is not None else {}
    if _only_raises_not_implemented(body):
        ctx.add("stub-raise", node, f"{name} only raises NotImplementedError.", **owner)
    elif _is_empty(body) and name != "__init__":
        ctx.add("stub-body", node, f"{name} has no body.", confidence=_stub_confidence(ctx, node, class_node), **owner)
    arguments = [arg.arg for arg in [*node.args.args, *node.args.kwonlyargs] if arg.arg not in ("self", "cls")]
    always_true = len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Constant) and body[0].value.value is True
    if always_true and looks_like_auth_check(node) and arguments:
        ctx.add("fake-success", node, f"{name} always returns True and ignores {', '.join(arguments)}.")


def _stub_confidence(ctx, node, class_node) -> str:
    """Empty hook methods on a working class are normal. A class of nothing but stubs, or an empty function, isn't. Empty is the point of a no-op or a handler handed to something else."""
    parameters = [arg.arg for arg in node.args.args]
    signal_handler = len(parameters) == 2 and "sig" in parameters[0].lower() and "frame" in parameters[1].lower() and node.name in ctx.referenced_as_values()
    if NO_OP_NAME.fullmatch(node.name) or (class_node is not None and NULL_OBJECT_CLASS.match(class_node.name)) or signal_handler:
        return "low"
    if class_node is None:
        return "medium" if _docstring(node) is not None else "high"
    methods = [m for m in class_node.body if isinstance(m, FUNCTION_NODES) and m.name != "__init__"]
    empty = [m for m in methods if not _body(m) or (len(_body(m)) == 1 and isinstance(_body(m)[0], (ast.Pass, ast.Raise)))]
    return "medium" if len(empty) == len(methods) else "low"


def _size_rules(ctx, node, name, length, complexity, params) -> None:
    if complexity >= 15:
        ctx.add("high-complexity", node, f"{name} has cyclomatic complexity {complexity}.", **({"severity": "high"} if complexity >= 30 else {}))
    if length > 100:
        ctx.add("long-function", node, f"{name} is {length} lines.", **({"severity": "high"} if length > 250 else {}))
    depth = _max_nesting(node.body)
    if depth > 4:
        ctx.add("deep-nesting", node, f"{name} nests {depth} levels.", **({"severity": "high"} if depth > 6 else {}))
    if len(params) > 7:
        ctx.add("many-params", node, f"{name} takes {len(params)} parameters.")
    defaults = node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
    flags = sum(1 for d in defaults if isinstance(d, ast.Constant) and isinstance(d.value, bool))
    if flags >= 3:
        ctx.add("flag-params", node, f"{name} has {flags} boolean flags.")


def _api_rules(ctx, node, name, body, params, decorator_last, complexity, class_node) -> None:
    _documentation(ctx, node, name, params, complexity)
    if not decorator_last and not name.startswith("__"):
        _pass_through(ctx, node, name, body)
    if class_node is None and name in HELPERS and len(body) >= 2:
        ctx.add("handrolled-helper", node, f"{name} reimplements {HELPERS[name]}.")
    _memo(ctx, node, name, body)
    nodes = list(_walk_own(node))
    if ENCRYPTION_NAME.search(name) and any(_is_xor_or_base64(n) for n in nodes):
        ctx.add("homemade-crypto", node, f"{name} uses XOR or base64 as encryption.")
    _return_shapes(ctx, node, nodes, name)
    if len(body) == 1 and isinstance(body[0], ast.Try):
        broad = [h for h in body[0].handlers if h.type is None or _last(_dotted(h.type)) in ("Exception", "BaseException")]
        if broad and not any(isinstance(n, ast.Raise) for h in broad for s in h.body for n in ast.walk(s)):
            ctx.add("broad-wrap", node, f"All of {name} is inside a broad try that doesn't re-raise.")


def _is_xor_or_base64(node: ast.AST) -> bool:
    return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitXor)) or (isinstance(node, ast.Call) and "b64" in _call_name(node))


def _documentation(ctx, node, name, params, complexity) -> None:
    document = _docstring(node)
    if not name.startswith("_") and document is None and (complexity >= 12 or len(params) >= 5) and not ctx.is_script:
        ctx.add("missing-docstring", node, f"{name} has complexity {complexity} and {len(params)} parameters, and no docstring.")
    if document and len(document) < 60 and "\n" not in document:
        words = {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z]+", document)} - DOCSTRING_FILLER
        name_words = {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z][a-z]*", name)}
        if words and words <= name_words:
            ctx.add("docstring-restates-name", node, f"The docstring only repeats '{name}'.")


def _pass_through(ctx, node, name, body) -> None:
    if not (len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call)):
        return
    call = body[0].value
    passed = [arg.id for arg in call.args if isinstance(arg, ast.Name)] + [k.value.id for k in call.keywords if isinstance(k.value, ast.Name)]
    own = [arg.arg for arg in node.args.args if arg.arg not in ("self", "cls")] + [arg.arg for arg in node.args.kwonlyargs]
    target = _call_name(call)
    if own and passed == own and len(call.args) + len(call.keywords) == len(own) and "super" not in target and _last(target) != name:
        ctx.add("pass-through", node, f"{name} only forwards to {target}().")


def _memo(ctx, node, name, body) -> None:
    first = body[0] if body else None
    if isinstance(first, ast.If) and isinstance(first.test, ast.Compare) and isinstance(first.test.ops[0], ast.In) and isinstance(first.test.comparators[0], ast.Name) \
            and first.test.comparators[0].id in ctx.module_mutables and isinstance(first.body[0], ast.Return):
        ctx.add("handrolled-memo", node, f"{name} memoizes by hand in {first.test.comparators[0].id}.")


def _return_shapes(ctx, node, nodes, name) -> None:
    shapes = set()
    bare = value = False
    for n in nodes:
        if isinstance(n, ast.Return):
            if n.value is None or (isinstance(n.value, ast.Constant) and n.value.value is None):
                bare = True
            else:
                value = True
                if isinstance(n.value, ast.Constant):
                    shapes.add(type(n.value.value).__name__)
                elif isinstance(n.value, (ast.Dict, ast.List, ast.Tuple, ast.Set, ast.JoinedStr)):
                    shapes.add(type(n.value).__name__)
    shapes = {"str" if s == "JoinedStr" else s for s in shapes}
    if len(shapes) >= 2 and not shapes <= {"int", "float"} and not name.startswith("__"):
        ctx.add("inconsistent-return", node, f"{name} returns {', '.join(sorted(shapes))} on different paths.")
    elif bare and value and shapes & {"bool"}:
        ctx.add("inconsistent-return", node, f"{name} returns a bool on some paths and None on others.")


def _naming(ctx, node, name, class_node) -> None:
    twin = TWIN_HEDGE.match(name)
    if not name.startswith("__") and (HEDGE_NAME.search(name) or (twin and twin.group("base") in ctx.function_names)):
        ctx.add("hedge-name", node, f"'{name}' records history rather than meaning.")
    if re.search(r"[a-z][A-Z]", name) and not name.startswith("__") and class_node is None:
        ctx.camel_defs.append(node)


def _reads_environment(statement: ast.AST) -> bool:
    return bool(re.search(r"environ|getenv", ast.dump(statement)))


def setting_names(ctx) -> dict[str, int]:
    """Settings a configuration module defines, and how often each appears in it. Others may read them, or nothing may.

    A setting is a field of a Config or Settings class, or a module-level value taken from the environment.
    """
    if not re.search(r"(?:^|/)(?:config|settings|conf)\.py$", ctx.path):
        return {}
    names = []
    for statement in ctx.tree.body:
        if isinstance(statement, ast.ClassDef) and re.search(r"Config|Settings", statement.name):
            scope = statement.body
        else:
            scope = [statement] if _reads_environment(statement) else []
        for inner in scope:
            target = inner.target if isinstance(inner, ast.AnnAssign) else inner.targets[0] if isinstance(inner, ast.Assign) else None
            if isinstance(target, ast.Name) and not target.id.startswith("_"):
                names.append(target.id)
    return {name: len(re.findall(rf"\b{re.escape(name)}\b", ctx.text)) for name in names}


def _frozen_default(ctx, node_default: ast.AST, label: str) -> None:
    if isinstance(node_default, ast.Call) and _call_name(node_default) in ONCE_ONLY_CALLS:
        ctx.add("frozen-default", node_default, f"{label} is computed once, when the module is imported.")


def _defaults(ctx, node) -> None:
    for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
        _frozen_default(ctx, default, f"The default of {node.name}")
        mutable = isinstance(default, (ast.List, ast.Dict, ast.Set)) or (isinstance(default, ast.Call) and _call_name(default) in ("list", "dict", "set"))
        if mutable:
            ctx.add("mutable-default", default, f"{node.name} has a mutable default argument.")


def _cache_decorator(ctx, decorator: ast.AST, class_node) -> None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = _last(_dotted(target))
    if name == "cache" and "functools" in _dotted(target) or (name == "cache" and class_node is not None):
        ctx.add("unbounded-cache", decorator, "This cache has no size limit" + (" and holds a reference to self." if class_node else "."))
    elif name == "lru_cache" and isinstance(decorator, ast.Call):
        for keyword in decorator.keywords:
            if keyword.arg == "maxsize" and isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                ctx.add("unbounded-cache", decorator, "lru_cache(maxsize=None) never evicts.")


def _is_fastapi_route(decorators: list[str]) -> bool:
    return any(re.search(r"\.(?:route|get|post|put|patch|delete|websocket)$", d) for d in decorators)


def _route_is_guarded(node, decorators: list[str]) -> bool:
    if any(AUTH_DECORATOR.search(d) for d in decorators if not _is_fastapi_route([d])):
        return True
    for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
        if isinstance(default, ast.Call) and _last(_call_name(default)) in ("Depends", "Security") and AUTH_DEPEND.search(ast.dump(default)):
            return True
    return any((isinstance(n, ast.Call) and AUTH_CALL.match(_last(_call_name(n)) or "")) or (isinstance(n, ast.Name) and n.id == "current_user") for n in ast.walk(node))


def _route(ctx, node, decorators: list[str]) -> None:
    ctx.routes.append({"name": node.name, "line": node.lineno, "guarded": _route_is_guarded(node, decorators), "node": node})
    from_request = _names_from_request(node)
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            _handler_call(ctx, inner, node.name)
            if _call_name(inner) in FILE_SINKS and from_request & {n for argument in inner.args for n in _names_in(argument)}:
                ctx.add("path-traversal", inner, f"{_call_name(inner)}() uses a value taken from the request.")


def _names_from_request(node) -> set[str]:
    """Locals in a handler assigned from the request: from its query, form, params or a body it was given."""
    names: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Assign) and any(isinstance(t, ast.Name) for t in inner.targets) and REQUEST_SOURCE.search(ast.dump(inner.value)):
            names.update(t.id for t in inner.targets if isinstance(t, ast.Name))
    return names


def _handler_call(ctx, call: ast.Call, handler: str) -> None:
    last = _last(_call_name(call))
    if last == "execute" and call.args and _has_sql(_string_parts(call.args[0])):
        ctx.add("sql-in-handler", call, f"Raw SQL inside the {handler} handler.")
    if last == "fetchall" or (last == "all" and _reads_a_whole_table(call)):
        ctx.add("unpaginated-query", call, f"{handler} loads every row.")


def _reads_a_whole_table(call: ast.Call) -> bool:
    if re.search(r"\.(?:query|objects)\b", _call_name(call)):
        return True
    if not (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Call)):
        return False
    chained = _call_name(call.func.value)
    return _last(chained) in ("query", "filter", "filter_by", "select", "execute", "scalars") and not re.search(r"limit|offset|paginate", ast.dump(call))


def check_class(ctx, node: ast.ClassDef) -> None:
    bases = [_dotted(base) for base in node.bases]
    methods = [s for s in node.body if isinstance(s, FUNCTION_NODES)]
    method_facts = {}
    for method in methods:
        hashed, statements = shape_hash(method)
        method_facts[method.name] = {"hash": hashed, "statements": statements, "line": method.lineno,
                                     "abstract": "abstractmethod" in {_last(d) for d in _decorator_names(method)}}
    abstract = (any(_last(b) in ("ABC", "Protocol") for b in bases) or any(m["abstract"] for m in method_facts.values())
                or any(isinstance(k.value, ast.Name) and k.value.id == "ABCMeta" for k in node.keywords))
    ctx.classes.append({"name": node.name, "line": node.lineno, "bases": [_last(b) for b in bases if b], "abstract": abstract,
                        "methods": method_facts, "kind": "class", "decorated": bool(node.decorator_list or node.keywords)})  # a metaclass, like a decorator, can build it another way
    if ctx.is_test or ctx.is_stub_file:
        return
    _class_names_and_size(ctx, node, methods)
    _class_field_defaults(ctx, node)
    _class_shape(ctx, node, methods, bases, abstract)
    if bases and not abstract and not ABSTRACT_NAME.search(node.name):
        for method in methods:
            if _only_raises_not_implemented(_body(method)):
                ctx.add("lsp-violation", method, f"{node.name}.{method.name} refuses a method it inherits.", owner=node.name)


def _only_raises_not_implemented(body: list) -> bool:
    return len(body) == 1 and isinstance(body[0], ast.Raise) and body[0].exc is not None and "NotImplementedError" in _names_in(body[0].exc)


def _class_field_defaults(ctx, node) -> None:
    for statement in node.body:
        if isinstance(statement, (ast.AnnAssign, ast.Assign)) and statement.value is not None:
            _frozen_default(ctx, statement.value, f"This field of {node.name}")


def _class_names_and_size(ctx, node, methods) -> None:
    length = (node.end_lineno or node.lineno) - node.lineno + 1
    if HEDGE_NAME.search(node.name.lower()):
        ctx.add("hedge-name", node, f"'{node.name}' records history rather than meaning.")
    if VAGUE_CLASS.search(node.name):
        ctx.add("vague-name", node, f"'{node.name}' doesn't say what it is responsible for.")
    if len(methods) > 30 or length > 800:
        ctx.add("god-class", node, f"{node.name} has {len(methods)} methods and {length} lines.")


def _class_shape(ctx, node, methods, bases, abstract) -> None:
    public = [m for m in methods if not m.name.startswith("_")]
    has_state = any(isinstance(s, (ast.Assign, ast.AnnAssign)) for s in node.body)
    static_only = len(methods) >= 2 and all({"staticmethod", "classmethod"} & {_last(d) for d in _decorator_names(m)} for m in methods)
    if static_only and not bases:
        ctx.add("static-only-class", node, f"{node.name} only has static methods.")
    elif (not bases and not has_state and not node.decorator_list and len(methods) == 2 and len(public) == 1
          and all(m.name in ("__init__", public[0].name) for m in methods)):
        ctx.add("one-method-class", node, f"{node.name} is one method plus a constructor.")
    if PATTERN_CLASS.search(node.name) and len(public) <= 1 and not abstract:
        ctx.add("pattern-one-product", node, f"{node.name} has {len(public)} public method.")


def _patched_target(call_or_decorator: ast.AST) -> str | None:
    args = getattr(call_or_decorator, "args", None)
    if args and isinstance(args[0], ast.Constant):
        return str(args[0].value)
    return None


def _test_evidence(ctx, node, name: str) -> dict:
    """What this test does: its asserts, the mocks it sets up, and whether it calls something that checks."""
    found = {"asserts": [], "mocks": 0, "patched": [], "checks": False}
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _last(_dotted(target)) in ("patch", "object"):
            found["mocks"] += 1
            found["patched"].append(_patched_target(decorator))
    own = {id(inner) for inner in _walk_own(node)}
    helpers = _checking_functions(ctx)
    for inner in ast.walk(node):  # asserts count in a nested `async def scenario()` too, a common way to write these
        if isinstance(inner, ast.Assert):
            found["asserts"].append(inner)
        elif isinstance(inner, ast.Call):
            found["checks"] = found["checks"] or _last(_call_name(inner)) in helpers
            if id(inner) in own:
                _test_call(ctx, inner, name, found)
            else:
                found["checks"] = found["checks"] or _is_checking_name(_last(_call_name(inner)))
        elif isinstance(inner, (ast.With, ast.AsyncWith)):
            found["checks"] = found["checks"] or any("raises" in ast.dump(item.context_expr) for item in inner.items)
        elif id(inner) in own and isinstance(inner, ast.Try) and any(h.type is None or _last(_dotted(h.type)) in ("Exception", "BaseException") for h in inner.handlers):
            ctx.add("test-swallows", inner, f"{name} catches broad exceptions.")
    return found


def _is_checking_name(name: str) -> bool:
    return bool(CHECKING_CALL.match(name.lstrip("_"))) or name in ("raises", "warns", "deprecated_call", "approx")


def _checking_functions(ctx) -> set[str]:
    """Functions in this file that assert, directly or through another, so that a test calling one does check something."""
    if ctx.checking_functions is None:
        functions = [n for n in ast.walk(ctx.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        calls = {id(f): {_last(_call_name(c)) for c in ast.walk(f) if isinstance(c, ast.Call)} for f in functions}
        found = {f.name for f in functions if any(isinstance(n, ast.Assert) for n in ast.walk(f)) or any(_is_checking_name(c) for c in calls[id(f)])}
        for _ in range(3):
            found |= {f.name for f in functions if calls[id(f)] & found}
        ctx.checking_functions = found
    return ctx.checking_functions


def _test_call(ctx, call: ast.Call, name: str, found: dict) -> None:
    called = _call_name(call)
    last = _last(called)
    if _is_checking_name(last):
        found["checks"] = True
        if last in ("raises", "assertRaises") and call.args and _last(_dotted(call.args[0])) in ("Exception", "BaseException"):
            ctx.add("test-broad-raises", call, "This accepts any exception.")
    if last in ("Mock", "MagicMock", "AsyncMock", "patch", "create_autospec"):
        found["mocks"] += 1
        if last == "patch":
            found["patched"].append(_patched_target(call))
    if called == "pytest.skip":
        ctx.add("test-skipped", call, f"{name} skips itself.")
    elif called == "time.sleep":
        ctx.add("test-sleep", call)


def _is_tautology(test: ast.AST) -> bool:
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.Tuple):  # `assert (x == 3, "message")` checks a tuple, not x
        return bool(test.elts)
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) and any(isinstance(value, ast.Constant) and value.value for value in test.values):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.GtE) and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value == 0:
        return (isinstance(test.left, ast.Call) and _call_name(test.left) == "len") or bool(COUNT_LIKE.search(_dotted(test.left) or ""))
    # Two calls can differ, and comparing them is how a test checks a singleton or a seed.
    return (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.Is))
            and ast.dump(test.left) == ast.dump(test.comparators[0]) and not any(isinstance(node, ast.Call) for node in ast.walk(test.left)))


def _test_function(ctx, node, name, decorator_last) -> None:
    if {"fixture", "pytest.fixture"} & decorator_last or not name.startswith("test"):
        return
    if GENERIC_TEST.match(name):
        ctx.add("test-generic-name", node, f"'{name}' doesn't describe a behavior.")
    if decorator_last & {"skip"} or any(d in ("pytest.mark.skip", "unittest.skip") for d in _decorator_names(node)):
        ctx.add("test-skipped", node, f"{name} is skipped.")
    found = _test_evidence(ctx, node, name)
    asserts = found["asserts"]
    if not asserts and not found["checks"]:
        ctx.add("test-no-assert", node, f"{name} doesn't assert anything.")
    for check in asserts:
        if _is_tautology(check.test):
            ctx.add("test-tautology", check, "This assertion can't fail.")
    if asserts and not found["checks"] and all(_is_weak_assert(check.test) for check in asserts):
        ctx.add("test-weak-assert", node, f"{name} only checks that something came back.")
    if found["mocks"] >= 4 and found["mocks"] > len(asserts):
        ctx.add("test-overmocked", node, f"{name} sets up {found['mocks']} mocks and has {len(asserts)} asserts.")
    subject = re.sub(r"^test_?", "", name)
    called = _replaced_then_called(node)
    if called:
        ctx.add("test-mocks-subject", node, f"{name} replaces {called} and then calls it, so it can only see the replacement.")
        return
    for target in filter(None, found["patched"]):
        leaf = target.rsplit(".", 1)[-1]
        if len(leaf) >= 4 and subject.startswith(leaf):
            ctx.add("test-mocks-subject", node, f"{name} patches {leaf}, which looks like its own subject.")
            break


MOCK_MACHINERY = re.compile(r"(?:monkeypatch|mocker|mock|unittest\.mock|patch)\.|(?:.*\.)?(?:assert_\w+|reset_mock|return_value|side_effect)$")


def _replacement(call: ast.Call) -> str | None:
    """The dotted name this call replaces, for `monkeypatch.setattr(mod, "x", fake)`, `patch.object(mod, "x")` and `patch("a.mod.x")`. A spy that keeps the original doesn't count."""
    if any(keyword.arg == "wraps" for keyword in call.keywords):
        return None
    args = call.args
    function = _call_name(call) or ""
    if _last(function) in ("setattr", "object") and len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
        owner = _dotted(args[0])
        target = f"{owner}.{args[1].value}" if owner else None
        keeps_original = target and any(_dotted(inner) == target for rest in args[2:] for inner in ast.walk(rest) if isinstance(inner, ast.Attribute))
        return None if keeps_original else target
    if _last(function) == "patch" and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
        return args[0].value
    return None


def _replaced_then_called(node) -> str | None:
    """Something the test replaces and then calls by its qualified name, when it calls nothing else that could be real code.

    A bare name isn't enough: after `from m import f`, `f` is still the real one. Calling anything else qualified means the test may
    only be feeding the replacement to real code, as in `gate.check(gate.load_manifest())`, which is a normal way to write one.
    """
    replaced: dict[str, int] = {}
    for decorator in node.decorator_list:
        target = _replacement(decorator) if isinstance(decorator, ast.Call) else None
        if target:
            replaced[target] = 0
    calls = sorted((inner for inner in ast.walk(node) if isinstance(inner, ast.Call)), key=lambda inner: inner.lineno)
    called = None
    for call in calls:
        target = _replacement(call)
        name = _call_name(call) or ""
        if target:
            replaced.setdefault(target, call.lineno)
        elif "." in name and not MOCK_MACHINERY.match(name):
            matched = next((target for target, line in replaced.items() if call.lineno > line and (target == name or target.endswith("." + name))), None)
            if not matched:
                return None
            called = matched
    return called


def _is_weak_assert(test: ast.AST) -> bool:
    if isinstance(test, (ast.Name, ast.Attribute)):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        right = test.comparators[0]
        if isinstance(test.ops[0], ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
            return True
        if isinstance(test.left, ast.Call) and _call_name(test.left) == "len" and isinstance(right, ast.Constant) and right.value == 0 and isinstance(test.ops[0], (ast.Gt, ast.NotEq)):
            return True
    return isinstance(test, ast.Call) and _call_name(test) == "isinstance"
