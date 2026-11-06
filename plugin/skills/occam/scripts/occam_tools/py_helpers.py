"""Shared vocabulary for the Python rules: name patterns, and small questions about AST nodes."""

from __future__ import annotations

import ast
import builtins
import hashlib
import re
from typing import Iterable

Found = tuple  # (rule, line, message or None, overrides)

AUTH_NAME = re.compile(
    r"(?:^|_)(?:verify|validate|authenticate|authorize|authorise|check_(?:auth|perm|access|token|signature|password|role|admin)"
    r"|is_(?:valid|auth|authenticated|authorized|allowed|admin|permitted|owner|member)|has_(?:perm|permission|access|role)|can_\w+)", re.I)
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
AUTH_DECORATOR = re.compile(r"login|auth|permission|require|jwt|protect|admin|token|role|guard", re.I)
AUTH_DEPEND = re.compile(r"auth|user|token|permission|admin|login|session|security|api_?key|verify", re.I)
PUBLIC_ROUTE = re.compile(r"health|ping|ready|live|status|metrics|login|logout|signin|signup|register|public|index|home|docs|openapi|webhook|callback|root|favicon|version|reset", re.I)
ROUTE_DECORATOR = {"route", "get", "post", "put", "patch", "delete", "api_view", "websocket"}
LOG_CALL = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "print", "fatal"}
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


def _has_sql(text: str) -> bool:
    return bool(re.search(r"\b(?:SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|WHERE|DROP\s+TABLE)\b", text, re.I))


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


def _only_placeholders(node: ast.AST, known: frozenset = frozenset()) -> bool:
    """An f-string that interpolates only a generated list of bind markers, as in IN ({marks}), or a module's constants, as in {TABLE}."""
    names = _names_in(node)
    return bool(names) and isinstance(node, ast.JoinedStr) and all(name.isupper() or name in known or re.fullmatch(r"(?:q|bind_?)?marks?|placeholders?|params_sql|qs", name, re.I) for name in names)


def _literal_loop_names(function: ast.AST | None) -> frozenset:
    """What a `for` over written-out strings binds, like `for table in ("a", "b"):`, since those values came from the code."""
    if function is None:
        return frozenset()
    return frozenset(loop.target.id for loop in ast.walk(function) if isinstance(loop, ast.For) and isinstance(loop.target, ast.Name)
                     and isinstance(loop.iter, (ast.Tuple, ast.List, ast.Set)) and all(isinstance(item, ast.Constant) for item in loop.iter.elts))


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
