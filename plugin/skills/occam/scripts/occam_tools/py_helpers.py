"""Shared vocabulary for the Python rules: name patterns, and small questions about AST nodes."""

from __future__ import annotations

import ast
import builtins
import hashlib
import re
from typing import Iterable, NamedTuple

Found = tuple  # (rule, line, message or None, overrides)

AUTH_NAME = re.compile(
    r"(?:^|_)(?:verify|validate|authenticate|authorize|authorise|login|check_(?:auth|perm|access|token|signature|password|role|admin|login|csrf)"
    r"|is_(?:auth|authenticated|authorized|allowed|admin|permitted|owner|member|logged_in)|has_(?:perm|permission|access|role))", re.I)
# These say nothing about auth on their own, as in can_retry(error) or is_valid_extension(name). What they're given, or a word in the name, has to.
MAYBE_AUTH_NAME = re.compile(r"(?:^|_)(?:can_\w+|is_valid\w*)", re.I)
AUTH_SUBJECT = re.compile(r"user|token|password|passwd|credential|request|session|role|principal|account", re.I)
AUTH_WORD_IN_NAME = re.compile(r"(?:^|_)(?:token|password|passwd|credentials?|session|role|login)(?:_|$)", re.I)
SECRET_NAME = re.compile(r"password|passwd|pwd|secret|token|api_?key|nonce|salt|otp|session_?id|csrf|private_?key", re.I)
COMPARED_SECRET = re.compile(r"hmac|api_?key|secret|password_?hash|expected_?token|auth_?token|access_?token"
                             r"|^_*(?:(?:expected|provided|computed|calculated|received|webhook|request|header|given|incoming|actual|supplied|client|stored)_)?signature$", re.I)
MIGRATION_PATH = re.compile(r"(?:^|/)(?:alembic|migrations?)/")
MONEY_NAME = re.compile(r"(?:^|_)(?:price|amount|total|balance|cost|fee|tax|subtotal|payment|invoice|charge|refund)s?(?:_|$)", re.I)
HEDGE_NAME = re.compile(r"(?:_v\d+|_old|_fixed|_final|_improved|_enhanced|_better|_backup|_orig)$|^(?:better|improved|enhanced|fixed|my|foo|bar|baz)_", re.I)
TWIN_HEDGE = re.compile(r"^(?P<base>.+?)(?:_new|_copy\d*|_updated|_temp|_tmp|_original|_\d+)$")
DYNAMIC_NAMESPACE = re.compile(r"\bglobals\(\)|\bvars\(\)|\blocals\(\)|\bsys\.modules\b|\b__dict__\b|\bexec\(|\b_convert_?\(|\bglobal_enum\b|\bsetattr\(sys")
VAGUE_CLASS = re.compile(r"(?:Manager|Helper|Util|Utils|Processor|Wrapper|Thing|Stuff)$")
PATTERN_CLASS = re.compile(r"(?:Factory|Builder|Strategy|Provider|Registry)$")
ABSTRACT_NAME = re.compile(r"(?:^|_)(?:Abstract|Base|Interface|Mixin|Protocol)|(?:Abstract|Base|Interface|Mixin|Protocol|ABC)$")
GENERIC_TEST = re.compile(r"^test_?(?:\d+|it|function|works?|basic\d*|foo|bar|test|something|case\d*|example\d*|main)?$")
# `require` alone isn't auth: @require_json and @require_POST check the request's shape.
AUTH_DECORATOR = re.compile(r"login|auth|permission|requires?_(?:user|perm)|jwt|protect|admin|token|role|guard", re.I)
# Called from a handler's body. `data = require_json(request)`, role_list() and token_count() guard nothing, so this goes by the whole name.
AUTH_CALL = re.compile(
    r"_*(?:require[sd]?_(?:login|auth|role|user|admin|perm|token|jwt|api_?key)"
    r"|(?:check|verify|validate|ensure|enforce|assert)_(?:auth|perm|access|token|jwt|role|admin|login|session|api_?key|logged)"
    r"|(?:get_)?current_(?:active_)?user|get_jwt_identity|authenticate|authori[sz]e|login_required|jwt_required|is_authenticated|has_(?:perm|permission|role|access))", re.I)
AUTH_DEPEND = re.compile(r"auth|user|token|permission|admin|login|session|security|api_?key|verify", re.I)
PUBLIC_ROUTE = re.compile(r"(?:^|_)(?:health|healthz|healthcheck|ping|ready|readyz|readiness|live|livez|liveness|status|metrics|login|logout|signin|signup|register|registration|public|index|home|homepage|docs|openapi"
                          r"|webhooks?|callbacks?|root|favicon|version|reset)(?:_|$)", re.I)
CHANGES_DATA_NAME = re.compile(r"_*(?:delete|update|change|reset_all|export)", re.I)  # update_order_status is about an order, however public a status check is
ROUTE_DECORATOR = {"route", "get", "post", "put", "patch", "delete", "api_view", "websocket"}
LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
ONCE_ONLY_CALLS = {"datetime.now", "datetime.utcnow", "datetime.datetime.now", "datetime.datetime.utcnow", "date.today", "datetime.date.today", "time.time",
                   "uuid.uuid4", "uuid4", "random.random", "os.getpid", "now", "utcnow", "time"}
NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.){0,200}[+*](?:[^()\\]|\\.){0,200}\)[+*]")
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
BLOCK_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)
if hasattr(ast, "TryStar"):
    BLOCK_NODES = (*BLOCK_NODES, ast.TryStar)
HTTP_MODULES = {"requests", "httpx"}
HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options", "request"}
QUERY_METHODS = {"execute", "fetch", "fetchrow", "fetchval", "scalar", "scalars", "query", "find_one", "get_item", "get_object", "put_object"}
HELPERS = {
    "chunk": "itertools.batched, or more-itertools", "chunks": "itertools.batched, or more-itertools", "batched": "itertools.batched",
    "flatten": "itertools.chain.from_iterable", "dedupe": "dict.fromkeys", "deduplicate": "dict.fromkeys", "unique": "dict.fromkeys",
    "deep_copy": "copy.deepcopy", "deepcopy": "copy.deepcopy", "ensure_dir": "os.makedirs(exist_ok=True)", "mkdir_p": "os.makedirs(exist_ok=True)",
    "slugify": "python-slugify", "is_valid_email": "email-validator", "validate_email": "email-validator",
    "parse_date": "datetime.fromisoformat, or dateutil", "parse_datetime": "datetime.fromisoformat, or dateutil",
    "retry": "tenacity or stamina", "with_retry": "tenacity or stamina", "retry_with_backoff": "tenacity or stamina",
    "levenshtein": "rapidfuzz", "edit_distance": "rapidfuzz", "human_size": "humanize", "humanize_bytes": "humanize",
    "merge_dicts": "the | operator, or a tested deep-merge library", "deep_merge": "a tested deep-merge library",
    "group_by": "itertools.groupby, or collections.defaultdict", "groupby": "itertools.groupby, or collections.defaultdict",
    "sha256_file": "hashlib.file_digest", "hash_file": "hashlib.file_digest", "camel_to_snake": "inflection", "snake_to_camel": "inflection",
    "load_env": "python-dotenv", "read_env": "python-dotenv", "get_logger": "logging.getLogger",
    "timer": "time.perf_counter, or a context manager you already have", "memoize": "functools.cache", "lru_cache": "functools.lru_cache",
}
KNOWN_NAMES = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__path__", "__class__", "__builtins__",
                                     "__annotations__", "__dict__", "__loader__", "__cached__", "__qualname__", "__module__", "__debug__",
                                     "WindowsError", "reveal_type", "reveal_locals", "_", "unicode", "basestring", "long", "xrange", "raw_input",
                                     "unichr", "cmp", "reduce", "file", "execfile", "reload", "get_ipython", "display", "exit", "quit"}


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _call_name(node: ast.Call) -> str:
    return _dotted(node.func)


def _chain(node: ast.AST) -> str:
    """`get_db().session.execute` as "get_db.session.execute": like `_dotted`, but it reads through calls and subscripts."""
    parts = []
    while True:
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))


def _last(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _body(function: ast.AST) -> list:
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


def _docstring(function: ast.AST) -> str | None:
    return ast.get_docstring(function, clean=True)


def _decorator_names(function: ast.AST) -> list[str]:
    names = []
    for decorator in getattr(function, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.append(_dotted(target))
    return names


def _is_constant_none_or_empty(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return node.value in (None, False, "", 0)
    return isinstance(node, (ast.List, ast.Dict, ast.Tuple, ast.Set)) and not getattr(node, "elts", getattr(node, "keys", []))


_SQL_TEXT = re.compile(
    r"\b(?:SELECT(?=[\s(*]|$)|WHERE(?=\s|$)|INSERT\s+(?:OR\s+\w+\s+)?INTO\b|REPLACE\s+INTO\b|MERGE\s+INTO\b|UPDATE\s+(?:\S+\s+)?SET\b|DELETE\s+FROM\b|PRAGMA\s|VACUUM\b|ATTACH\s+DATABASE\b|TRUNCATE\s+TABLE\b|ALTER\s+TABLE\b"
    r"|(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(?:UNIQUE\s+)?(?:TABLE|INDEX|VIEW|TRIGGER|DATABASE|SCHEMA|SEQUENCE|TYPE|EXTENSION|COLUMN)\b)", re.I)
PLACEHOLDER_NAME = re.compile(r"(?:q|bind_?)?marks?|placeholders?|params_sql|qs", re.I)
_BIND_MARKER = re.compile(r"\?\d*|%s|%\(\w+\)s|\$\d*|[:@]\w*|\bNULL\b", re.I)
_MARKER_MAKER = re.compile(r"placeholder|marks?\b|bind", re.I)
SQL_NUMBER_CALLS = {"int", "float", "len"}


def _has_sql(text: str) -> bool:
    return bool(_SQL_TEXT.search(text))


def _string_parts(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return " ".join(_string_parts(value) for value in node.values)
    if isinstance(node, ast.BinOp):
        return _string_parts(node.left) + " " + _string_parts(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _string_parts(node.func.value)
    return ""


def _is_dynamic_string(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(value, ast.FormattedValue) for value in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        if isinstance(node.op, ast.Add) and any(isinstance(side, (ast.List, ast.Tuple)) for side in (node.left, node.right)):
            return False  # an argument list being joined, not text
        return not (isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant))
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format" and bool(_string_parts(node.func.value))


def _interpolated(node: ast.AST) -> list[ast.AST]:
    """What a dynamic string puts into its text, for each way of building one."""
    if isinstance(node, ast.Constant):
        return []
    if isinstance(node, ast.JoinedStr):
        return [value.value for value in node.values if isinstance(value, ast.FormattedValue)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _interpolated(node.left) + _interpolated(node.right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        filled = node.right.elts if isinstance(node.right, ast.Tuple) else [value for value in node.right.values if value is not None] if isinstance(node.right, ast.Dict) else [node.right]
        return _interpolated(node.left) + list(filled)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _interpolated(node.func.value) + list(node.args) + [keyword.value for keyword in node.keywords]
    return [node]


def builds_bind_markers(node: ast.AST) -> bool:
    """Text made of nothing but bind markers, however many: `",".join("?" * len(ids))`, or a helper named for making them."""
    if isinstance(node, ast.Call) and _MARKER_MAKER.search(_last(_chain(node.func))):
        return True
    parts = [child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)]
    return any(_BIND_MARKER.search(part) for part in parts) and not any(_BIND_MARKER.sub("", part).strip(" ,()\n\t") for part in parts)


class Binding(NamedTuple):
    node: ast.AST            # what binds the name
    value: ast.AST | None    # what it's set to, or for a loop what it runs over. None when that can't be read off


def scope_bindings(scope: ast.AST) -> dict[str, list[Binding]]:
    """Everything one function or module binds, and to what. A comprehension or nested function has its own scope."""
    found: dict[str, list[Binding]] = {}

    def add(name: str, node: ast.AST, value: ast.AST | None = None) -> None:
        found.setdefault(name, []).append(Binding(node, value))

    def bind(target: ast.AST, node: ast.AST, value: ast.AST | None) -> None:
        if isinstance(target, ast.Name):
            add(target.id, node, value)
        elif isinstance(target, (ast.Tuple, ast.List, ast.Starred)):
            for name in _names_in(target):  # unpacked, so which part it gets isn't worked out
                add(name, node)

    arguments = getattr(scope, "args", None)
    if arguments is not None:
        for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]:
            if arg is not None:
                add(arg.arg, arg)
    stack = list(scope.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (*FUNCTION_NODES, ast.ClassDef)):
            add(node.name, node)
            continue
        if isinstance(node, (ast.Lambda, *COMPREHENSIONS)):
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bind(target, node, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if node.value is not None:
                bind(node.target, node, node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bind(node.target, node, node.iter)
        elif isinstance(node, ast.NamedExpr):
            bind(node.target, node, node.value)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    bind(item.optional_vars, node, None)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            add(node.name, node)
        elif isinstance(node, ast.alias):
            add((node.asname or node.name).split(".")[0], node)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                add(name, node)
        elif type(node).__name__ in ("MatchAs", "MatchStar") and node.name:
            add(node.name, node)
        elif type(node).__name__ == "MatchMapping" and node.rest:
            add(node.rest, node)
        stack.extend(ast.iter_child_nodes(node))
    for listed in found.values():
        listed.sort(key=lambda binding: _starts_at(binding.node))
    return found


def _is_literal(value: ast.AST | None, upper: bool) -> bool:
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Name):
        return upper and value.id.isupper()
    if isinstance(value, ast.JoinedStr):
        return not any(isinstance(part, ast.FormattedValue) for part in value.values)
    if isinstance(value, ast.IfExp):
        return _is_literal(value.body, upper) and _is_literal(value.orelse, upper)
    return isinstance(value, ast.BinOp) and _is_literal(value.left, upper) and _is_literal(value.right, upper)


def _is_literal_iterable(iterable: ast.AST | None, upper: bool) -> bool:
    if isinstance(iterable, ast.Name):
        return upper and iterable.id.isupper()
    return isinstance(iterable, (ast.Tuple, ast.List, ast.Set)) and all(_is_literal(item, upper) for item in iterable.elts)


def is_literal_binding(binding: Binding, upper: bool = False) -> bool:
    """Whether this binding takes a value written in the code. `upper` also takes a module's constant, as in `for table in TABLES:`."""
    if isinstance(binding.node, (ast.For, ast.AsyncFor)):
        return _is_literal_iterable(binding.value, upper)
    return _is_literal(binding.value, upper)


def comprehension_scopes(statement: ast.AST) -> dict[int, dict[str, bool]]:
    """For each call inside a comprehension, the names its comprehensions bind, and whether each only takes written-out values. It applies there and nowhere else."""
    found: dict[int, dict[str, bool]] = {}
    stack: list[tuple[ast.AST, dict[str, bool]]] = [(statement, {})]
    while stack:
        node, bound = stack.pop()
        if isinstance(node, COMPREHENSIONS):
            bound = dict(bound)
            for generator in node.generators:
                for name in _names_in(generator.target):
                    bound[name] = isinstance(generator.target, ast.Name) and _is_literal_iterable(generator.iter, True)
        elif isinstance(node, ast.Call) and bound:
            found[id(node)] = bound
        stack.extend((child, bound) for child in ast.iter_child_nodes(node))
    return found


def _starts_at(node: ast.AST) -> tuple[int, int]:
    return getattr(node, "lineno", 0), getattr(node, "col_offset", 0)


def holds_at(bindings: list[Binding], call: ast.AST) -> list[ast.AST]:
    """The text a name holds at this call: its last assignment before it, plus up to a few appends since. Nothing readable if a loop or anything else bound it last. `bindings` come in source order."""
    low, high = 0, len(bindings)
    while low < high:
        middle = (low + high) // 2
        if _starts_at(bindings[middle].node) < _starts_at(call):
            low = middle + 1
        else:
            high = middle
    held: list[ast.AST] = []
    for binding in reversed(bindings[max(0, low - 8):low]):
        node = binding.node
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and (node.end_lineno, node.end_col_offset) > (call.lineno, call.col_offset):
            continue  # `sql = conn.execute(sql)`: this call is part of that statement
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            held.append(binding.value)
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and binding.value is not None:
            held.append(binding.value)
        break
    return held[::-1]


def looks_like_auth_check(function: ast.AST) -> bool:
    """By its name, and for the names that need it, by what it's given."""
    if AUTH_NAME.search(function.name):
        return True
    if not MAYBE_AUTH_NAME.search(function.name):
        return False
    arguments = function.args
    given = [arg.arg for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs] if arg.arg not in ("self", "cls")]
    return bool(AUTH_WORD_IN_NAME.search(function.name)) or any(AUTH_SUBJECT.search(name) for name in given)


def is_public_route(name: str) -> bool:
    """Routes that are public by nature. A word has to stand alone, because `delivery` isn't `live`, and doing something to one isn't serving it."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return bool(PUBLIC_ROUTE.search(snake)) and not CHANGES_DATA_NAME.match(snake)


def _names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _complexity(function: ast.AST) -> int:
    score = 1
    for node in _walk_own(function):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert)):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
        elif type(node).__name__ == "match_case":
            score += 1
    return score


def _walk_own(function: ast.AST) -> Iterable[ast.AST]:
    """Walk a function without descending into nested functions or classes."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*FUNCTION_NODES, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _max_nesting(statements: list, depth: int = 0) -> int:
    deepest = depth
    for statement in statements:
        if isinstance(statement, FUNCTION_NODES + (ast.ClassDef,)):
            continue
        if isinstance(statement, BLOCK_NODES):
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(statement, field, [])
                is_elif = field == "orelse" and len(inner) == 1 and isinstance(inner[0], ast.If)
                deepest = max(deepest, _max_nesting(inner, depth if is_elif else depth + 1))
            for handler in getattr(statement, "handlers", []):
                deepest = max(deepest, _max_nesting(handler.body, depth + 1))
    return deepest


def shape_hash(function: ast.AST) -> tuple[str, int]:
    """A hash of a function's structure with local names and literal values abstracted, and its statement count."""
    names: dict[str, int] = {}
    tokens: list[str] = []
    statements = 0
    for node in ast.walk(function):
        if isinstance(node, ast.stmt):
            statements += 1
        if isinstance(node, ast.Name):
            tokens.append(f"n{names.setdefault(node.id, len(names))}")
        elif isinstance(node, ast.arg):
            tokens.append(f"n{names.setdefault(node.arg, len(names))}")
        elif isinstance(node, ast.Attribute):
            tokens.append("." + node.attr)
        elif isinstance(node, ast.Constant):
            tokens.append(type(node.value).__name__)
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            tokens.append("def")
        else:
            tokens.append(type(node).__name__)
    return hashlib.sha1(" ".join(tokens).encode()).hexdigest()[:16], statements


def head_is_re(name: str) -> bool:
    return name.split(".")[0] in ("re", "regex")
