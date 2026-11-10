"""Python rules for trust boundaries the main walk can't see in one call: who a handler scopes data to, what an agent is allowed, what leaves
in a log or an error, and checks that look like guards but let the attack through. Each reads the whole tree on its own.

docs/quality-catalog.md says which failure each answers. None of these reaches high confidence, so they show as leads in `scan` and `gate`
and never send an agent back on their own.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

from .py_helpers import ROUTE_DECORATOR_NAME as _ROUTE, _walk_own
from .rules_py_agent import _COMMITS as _SESSIONS, FUNCTIONS, _is_log_call, _logged_values, _text
from .rules_py_semantics import _exits, _functions

_GET_ONLY = re.compile(r"(?:^|\.)get$")


def _decorator_names(function: ast.AST) -> list[str]:
    return [_text(decorator.func if isinstance(decorator, ast.Call) else decorator) for decorator in function.decorator_list]


_ERROR_RESPONSE = re.compile(r"(?:^|\.)(?:abort|HTTPException|HttpResponse(?:Forbidden|BadRequest|NotAllowed)|PermissionDenied|ValidationError|\w*Error)$")


def _refuses(statements: list) -> bool:
    """Ends in a refusal: raising, aborting, returning None or False, or returning an error response or a `(body, 4xx)` pair. Returning a
    different URL, as `if host == "localhost": return "http://localhost:8000"` does, isn't one."""
    last = statements[-1] if statements else None
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.Expr) and isinstance(last.value, ast.Call):
        return bool(_ERROR_RESPONSE.search(_text(last.value.func)))
    if not isinstance(last, ast.Return):
        return False
    value = last.value
    if value is None or (isinstance(value, ast.Constant) and value.value in (None, False)):
        return True
    if isinstance(value, ast.Tuple) and len(value.elts) >= 2 and isinstance(value.elts[1], ast.Constant) and isinstance(value.elts[1].value, int):
        return 400 <= value.elts[1].value < 600
    return isinstance(value, ast.Call) and bool(_ERROR_RESPONSE.search(_text(value.func)) or any(
        keyword.arg in ("status", "status_code") and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, int) and keyword.value.value >= 400
        for keyword in value.keywords))


# ---------------------------------------------------------------- what an agent is allowed

_SKIPS_APPROVAL = re.compile(r"^--(?:dangerously-skip-permissions|dangerously-bypass-approvals-and-sandbox)$|^--permission-mode=bypassPermissions$")
_AGENT_CALL = re.compile(r"agent|claude|codex", re.I)


def _whole_environment(value: ast.AST) -> bool:
    """`os.environ`, `dict(os.environ)`, `os.environ.copy()` or `{**os.environ, ...}`: everything this process holds."""
    if isinstance(value, ast.Dict):
        return any(key is None and _whole_environment(item) for key, item in zip(value.keys, value.values))
    if isinstance(value, ast.Call):
        if _text(value.func) in ("dict", "os.environ.copy") and (value.args or _text(value.func) == "os.environ.copy"):
            return _text(value.func) == "os.environ.copy" or _whole_environment(value.args[0])
        return False
    return _text(value) == "os.environ"


def _agent_permissions(tree: ast.Module) -> Iterator[tuple]:
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        name = _text(node.func)
        for keyword in node.keywords:
            value = keyword.value.value if isinstance(keyword.value, ast.Constant) else None
            if (keyword.arg in ("permission_mode", "permissionMode") and value == "bypassPermissions") or (keyword.arg == "approval_policy" and value == "never") \
                    or (keyword.arg in ("sandbox", "sandbox_mode") and value == "danger-full-access"):
                yield ("agent-permission-widened", node.lineno, f"`{keyword.arg}={value!r}` lets the agent run every tool without a person approving it. "
                       "Someone should choose that knowingly, for a task that needs it.", {})
            elif keyword.arg == "env" and _AGENT_CALL.search(name) and _whole_environment(keyword.value):
                yield ("agent-permission-widened", node.lineno, "This hands the agent every variable in this process's environment, including credentials "
                       "its task doesn't need. Pass only the ones it does.", {})
        flags = [item for argument in node.args for item in (argument.elts if isinstance(argument, (ast.List, ast.Tuple)) else [argument])]
        if any(isinstance(flag, ast.Constant) and isinstance(flag.value, str) and _SKIPS_APPROVAL.match(flag.value) for flag in flags):
            yield "agent-permission-widened", node.lineno, "This starts an agent with approvals turned off, so it acts with no person checking.", {}


# ---------------------------------------------------------------- credentials leaving in logs and errors

_REQUEST_OWNER = re.compile(r"(?:^|\.)(?:req|request|prepared|prepped|prep|session|sess|http_session)$")
_HEADER_FIELDS = {"headers", "META"}
_RESPONDS = {"HTTPException", "JSONResponse", "jsonify", "Response", "JsonResponse", "HttpResponse", "make_response", "abort", "PlainTextResponse"}


def _requests_in(function: ast.AST) -> set[str]:
    """Names this function binds to a request object, as `req = resp.request`."""
    return {node.targets[0].id for node in _walk_own(function) if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) and _REQUEST_OWNER.search(_text(node.value))}


def _carries_request_headers(value: ast.AST, requests: set[str]) -> bool:
    """The headers of a request, as given or copied whole: `req.headers`, `dict(req.headers)`, `{**req.headers}`, `req.headers.items()`.
    A call to anything else, such as `redact(req.headers)`, has had its say about what goes out."""
    while True:
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ("dict", "str", "list", "repr", "sorted") and value.args:
            value = value.args[0]
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr in ("items", "copy", "dumps") and not value.args:
            value = value.func.value
        elif isinstance(value, ast.Call) and _text(value.func) == "json.dumps" and value.args:
            value = value.args[0]
        elif isinstance(value, ast.Dict):
            return any(key is None and _carries_request_headers(item, requests) for key, item in zip(value.keys, value.values))
        else:
            break
    if not (isinstance(value, ast.Attribute) and value.attr in _HEADER_FIELDS):
        return False
    owner = _text(value.value)
    return bool(_REQUEST_OWNER.search(owner)) or owner in requests


def _values_in(node: ast.AST) -> Iterator[ast.AST]:
    """Each value a literal holds, nested in dicts, lists and keyword arguments."""
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        if isinstance(item, ast.Dict):
            stack.extend(value for value in item.values if value is not None)
        elif isinstance(item, (ast.List, ast.Tuple, ast.Set)):
            stack.extend(item.elts)
        elif isinstance(item, ast.JoinedStr):
            stack.extend(part.value for part in item.values if isinstance(part, ast.FormattedValue))


def _header_leaks(tree: ast.Module) -> Iterator[tuple]:
    """A request's headers hold its Authorization and cookies, so logging them, or sending them back in an error, hands out the credential."""
    helpers = set()
    for function in _functions(tree):
        requests = _requests_in(function)
        if any(isinstance(node, ast.Return) and node.value is not None and any(_carries_request_headers(value, requests) for value in _values_in(node.value))
               for node in _walk_own(function)):
            helpers.add(function.name)
    for function in _functions(tree):
        requests = _requests_in(function)
        for node in (node for node in _walk_own(function) if isinstance(node, ast.Call)):
            given = [*node.args, *(keyword.value for keyword in node.keywords)]
            if _is_log_call(node):
                logged = [*_logged_values(node), *(keyword.value for keyword in node.keywords)]
                if any(_carries_request_headers(value, requests) for item in logged for value in _values_in(item)):
                    yield ("sensitive-log", node.lineno, "This logs a request's headers, which carry its Authorization credential and cookies. Log the "
                           "method and URL, or redact the sensitive headers first.", {})
            elif _text(node.func).rsplit(".", 1)[-1] in _RESPONDS:
                values = [value for item in given for value in _values_in(item)]
                if any(_carries_request_headers(value, requests) for value in values) or any(
                        isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in helpers for value in values):
                    yield ("error-details-exposed", node.lineno, "This sends a request's headers back to the caller, and they carry the credential it "
                           "was sent with. Return the status and a short message, and log the details with the headers redacted.", {})


# ---------------------------------------------------------------- client input that picks fields, paths or hosts

_RAW_REQUEST = re.compile(r"\brequest\.(?:get_json|json|form|data|values|POST|GET|args|query_params)\b|\bjson\.loads\(\s*request\.(?:body|data)")


def _allow_listed_keys(function: ast.AST) -> tuple[set[str], bool]:
    """What the function checks keys against, read once: names tested with `in` against something, or used to look up a module constant,
    and whether it compares the payload's keys as a set, as `set(data) - ALLOWED` does."""
    tested, set_difference = set(), False
    for node in _walk_own(function):
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops) and isinstance(node.left, ast.Name):
            tested.add(node.left.id)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id.isupper() and isinstance(node.slice, ast.Name):
            tested.add(node.slice.id)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Sub, ast.BitAnd)) and re.match(r"(?:set|frozenset)\(|\w+\.keys\(\)", _text(node.left)[:40]):
            set_difference = True
    return tested, set_difference


def _mass_assignment(tree: ast.Module) -> Iterator[tuple]:
    """`for key, value in request.get_json().items(): setattr(obj, key, value)` sets whatever field the client names, owner and plan included.
    A schema's `.model_dump()` or `.dict()` is fine: the schema is the allow-list."""
    for function in _functions(tree):
        source = _text(function)
        if not _RAW_REQUEST.search(source):
            continue
        raw = {node.targets[0].id for node in _walk_own(function) if isinstance(node, ast.Assign) and len(node.targets) == 1
               and isinstance(node.targets[0], ast.Name) and _RAW_REQUEST.search(_text(node.value))}
        tested, set_difference = _allow_listed_keys(function)
        if set_difference:
            continue
        for loop in (node for node in _walk_own(function) if isinstance(node, (ast.For, ast.AsyncFor))):
            if not (isinstance(loop.target, ast.Tuple) and len(loop.target.elts) == 2 and isinstance(loop.target.elts[0], ast.Name)):
                continue
            iterated = loop.iter.func.value if isinstance(loop.iter, ast.Call) and isinstance(loop.iter.func, ast.Attribute) and loop.iter.func.attr == "items" else None
            if iterated is None or not (_text(iterated) in raw or _RAW_REQUEST.search(_text(iterated))):
                continue
            key = loop.target.elts[0].id
            sets = [node for node in ast.walk(loop) if isinstance(node, ast.Call) and _text(node.func) == "setattr" and len(node.args) == 3 and _text(node.args[1]) == key]
            if sets and key not in tested:
                yield ("mass-assignment", sets[0].lineno, "This sets every field the client sends onto the object, so it can change ones it shouldn't, "
                       "such as an owner, a plan or a flag. Name the fields a client may set.", {})
                break


_REAL_PATH = re.compile(r"(?:^|\.)(?:realpath|abspath|normpath|resolve)$")
_SEPARATOR = re.compile(r"(?:os\.sep|os\.path\.sep|[\"']/[\"']|/[\"'])\s*\)?$")
_JOINED_WITH_EMPTY = re.compile(r"os\.path\.join\([^()]*,\s*[\"']{2}\)$")
_CHECKS_THE_BOUNDARY = re.compile(r"os\.(?:path\.)?sep\b|\bsep\b")  # `p.startswith(root) and p[len(root)] == os.sep`


def _text_closes_the_root(text: str) -> bool:
    """`base + os.sep`, `f"{base}/"` or `os.path.join(base, "")`, by the expression's text."""
    return bool(_SEPARATOR.search(text) or _JOINED_WITH_EMPTY.search(text))


def _value_closes_the_root(value: ast.AST | None) -> bool:
    """What a name holding the root was set to ends it with a separator, as text or as a string ending in one."""
    if value is None:
        return False
    return _text_closes_the_root(_text(value)) or (isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.endswith(("/", "\\")))


def _held_name(root: ast.AST, text: str) -> str | None:
    """The name a root is held under: a variable, or a self attribute."""
    if isinstance(root, ast.Name):
        return root.id
    return text if text.startswith("self.") else None


def _ends_with_separator(ctx_bindings: dict, root: ast.AST, held_elsewhere: dict) -> bool:
    """`base + os.sep`, `f"{base}/"`, `os.path.join(base, "")`, or a name or self attribute set to one: in this function, on self anywhere
    in the module, or as a module constant such as `UPLOAD_ROOT = "/srv/uploads/"`."""
    text = _text(root)
    if isinstance(root, ast.Tuple) or _text_closes_the_root(text):
        return True
    held = _held_name(root, text)
    return held is not None and any(_value_closes_the_root(value) for value in [*ctx_bindings.get(held, []), *held_elsewhere.get(held, [])])


def _roots_held_elsewhere(tree: ast.Module) -> dict[str, list]:
    """Values set on self anywhere in the module, then module constants, by name: where a root a function checks against may be set."""
    held: dict[str, list] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute) and _text(node.targets[0]).startswith("self."):
            held.setdefault(_text(node.targets[0]), []).append(node.value)
    for node in (node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None):
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
            if isinstance(target, ast.Name):
                held.setdefault(target.id, []).append(node.value)
    return held


def _local_assignments(function: ast.AST) -> dict[str, list]:
    assigned: dict[str, list] = {}
    for node in _walk_own(function):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigned.setdefault(node.targets[0].id, []).append(node.value)
    return assigned


def _resolves_a_path(expression: ast.AST) -> bool:
    return any(isinstance(inner, ast.Call) and _REAL_PATH.search(_text(inner.func)) for inner in ast.walk(expression))


def _containment_guards(function: ast.AST) -> Iterator[ast.If]:
    """Ifs that refuse on one side and don't already check the separator after the root."""
    for node in _walk_own(function):
        if isinstance(node, ast.If) and (_exits(node.body) or _exits(node.orelse)) and not _CHECKS_THE_BOUNDARY.search(_text(node.test)):
            yield node


def _startswith_calls(test: ast.AST) -> Iterator[ast.Call]:
    return (node for node in ast.walk(test) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith")


def _weak_path_checks(tree: ast.Module) -> Iterator[tuple]:
    """`if not resolved.startswith(base): raise` lets `/data/tenants/12` past a base of `/data/tenants/1`, since nothing ends the base.
    A root held on self is read from wherever this module sets it, as `self._prefix2 = self._prefix + "/"`."""
    elsewhere = _roots_held_elsewhere(tree)
    for function in _functions(tree):
        assigned = _local_assignments(function)
        resolved = {name for name, values in assigned.items() if any(_resolves_a_path(value) for value in values)}
        for guard in _containment_guards(function):
            for call in _startswith_calls(guard.test):
                receiver = call.func.value
                checks_a_real_path = (isinstance(receiver, ast.Name) and receiver.id in resolved) or _resolves_a_path(receiver)
                if checks_a_real_path and len(call.args) == 1 and not _ends_with_separator(assigned, call.args[0], elsewhere):
                    yield ("weak-path-check", call.lineno, f"{_text(call)[:60]} also accepts a sibling whose name starts the same, such as `{_text(call.args[0])[:30]}2`, "
                           "since the root has no trailing separator. Compare with os.path.commonpath, or use Path.is_relative_to.", {})


_LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]", "169.254.169.254", "metadata.google.internal", "metadata"}
_FETCHES = re.compile(r"\b(?:requests|httpx|aiohttp|urllib3)\.|\burlopen\(|\bAsyncClient\(|\bClientSession\(")
_CHECKS_ADDRESSES = re.compile(r"\bipaddress\b|\bis_private\b|\bis_loopback\b|\bis_global\b|\bis_link_local\b|\bgetaddrinfo\b|\bgethostbyname\b")


def _names_loopback(node: ast.AST, constants: dict[str, ast.AST]) -> bool:
    if isinstance(node, ast.Name) and node.id in constants:
        node = constants[node.id]
    if isinstance(node, ast.Call) and node.args and _text(node.func) in ("set", "frozenset", "tuple", "list"):
        node = node.args[0]
    items = node.elts if isinstance(node, (ast.Set, ast.List, ast.Tuple)) else [node]
    return any(isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value.lower() in _LOOPBACK for item in items)


def _ssrf_denylists(tree: ast.Module, text: str) -> Iterator[tuple]:
    """Refusing a few hostnames by name leaves decimal and IPv6 spellings, internal DNS names, other private ranges and redirects open."""
    if not _FETCHES.search(text) or _CHECKS_ADDRESSES.search(text):
        return
    constants = {node.targets[0].id: node.value for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    for guard in (node for node in ast.walk(tree) if isinstance(node, ast.If) and _refuses(node.body)):
        for compare in (node for node in ast.walk(guard.test) if isinstance(node, ast.Compare)):
            if any(isinstance(op, (ast.In, ast.Eq)) and _names_loopback(side, constants) for op, side in zip(compare.ops, compare.comparators)):
                yield ("ssrf", guard.lineno, "This refuses a few hostnames by name, which decimal and IPv6 spellings, internal DNS names, other private "
                       "ranges and redirects all get past. Resolve the host, refuse private, loopback and link-local addresses, and check again after "
                       "each redirect, or allow-list the hosts.", {})
                return


# ---------------------------------------------------------------- cookie-authenticated GETs that change data

_COOKIE_GUARD = re.compile(r"(?:^|\.)(?:login_required|fresh_login_required)$")
_UNSAFE_METHODS = re.compile(r"POST|PUT|PATCH|DELETE")
_NOT_A_CHANGE = re.compile(r"(?:^|_)(?:login|logout|signout|callback|oauth|authorize|sso)(?:_|$)", re.I)
_QUERY_STEPS = {"filter", "filter_by", "where", "exclude", "all"}


def _is_db_write(call: ast.Call) -> bool:
    """A commit, a model's save() or delete(), or a create or bulk update through the ORM."""
    if not isinstance(call.func, ast.Attribute):
        return False
    method, receiver = call.func.attr, call.func.value
    last = _text(receiver).rsplit(".", 1)[-1]
    if method == "commit" and not call.args:
        return last in _SESSIONS
    if method == "save":  # a model's save takes no positional arguments, unlike an image's save(path)
        return not call.args and not any(keyword.arg == "commit" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False for keyword in call.keywords)
    if method == "delete":
        return not call.args or last in _SESSIONS
    if method in ("create", "get_or_create", "update_or_create", "bulk_create", "update") and last == "objects":
        return True
    return method in ("update", "delete") and isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute) and receiver.func.attr in _QUERY_STEPS


def _serves_get(function: ast.AST, owner: ast.ClassDef | None) -> bool:
    """Flask or FastAPI's `@bp.get`, `@app.route` with no unsafe method in methods, a Django view nothing limits to POST, or a view class's get()."""
    if owner is not None:
        return function.name == "get"
    for decorator in (item for item in function.decorator_list if isinstance(item, ast.Call)):
        name = _text(decorator.func)
        if _GET_ONLY.search(name):
            return True
        if name.endswith(".route"):
            methods = next((keyword.value for keyword in decorator.keywords if keyword.arg == "methods"), None)
            return methods is None or not _UNSAFE_METHODS.search(_text(methods).upper())
        if name.endswith("require_http_methods"):
            return "GET" in _text(decorator).upper()
    names = _decorator_names(function)
    if any(name.endswith("require_POST") for name in names):
        return False
    return bool(function.args.args) and function.args.args[0].arg == "request"


def _cookie_guarded(function: ast.AST, owner: ast.ClassDef | None) -> bool:
    if owner is not None:
        return any("LoginRequired" in _text(base) for base in owner.bases)
    return any(_COOKIE_GUARD.search(name) for name in _decorator_names(function))


def _post_only(test: ast.AST, posted_form: bool) -> bool:
    """A branch a GET doesn't take: one testing request.method, a Flask-WTF `validate_on_submit()`, or the `is_valid()` of a form bound to
    request.POST, which on a GET is unbound and never valid."""
    text = _text(test)
    return "request.method" in text or "validate_on_submit(" in text or (posted_form and ".is_valid(" in text)


def _write_on_the_get_path(function: ast.AST) -> ast.Call | None:
    """The first write a GET reaches. Writes under a POST-only branch don't count, nor anything after an early
    `if request.method != "POST": return ...`."""
    posted_form = bool(re.search(r"request\.(?:POST|FILES)\b", _text(function)))
    guarded: set[int] = set()
    for node in _walk_own(function):
        if isinstance(node, ast.If) and _post_only(node.test, posted_form):
            guarded.update(id(inner) for statement in node.body for inner in ast.walk(statement))
    for index, statement in enumerate(function.body):
        if isinstance(statement, ast.If) and "request.method" in _text(statement.test) and _exits(statement.body):
            guarded.update(id(inner) for later in function.body[index + 1:] for inner in ast.walk(later))
            break
    return next((node for node in _walk_own(function) if isinstance(node, ast.Call) and id(node) not in guarded and _is_db_write(node)), None)


def _state_changing_gets(tree: ast.Module) -> Iterator[tuple]:
    """A browser sends its cookies with a cross-site GET, from a link or an image, and CSRF protection only covers the unsafe methods."""
    candidates = [(node, None) for node in tree.body if isinstance(node, FUNCTIONS)]
    candidates += [(item, node) for node in tree.body if isinstance(node, ast.ClassDef) for item in node.body if isinstance(item, FUNCTIONS)]
    for function, owner in candidates:
        if _NOT_A_CHANGE.search(function.name) or not _cookie_guarded(function, owner) or not _serves_get(function, owner):
            continue
        write = _write_on_the_get_path(function)
        if write is not None:
            yield ("state-change-on-get", write.lineno, f"{function.name} changes data on a GET behind the session cookie, and CSRF protection doesn't "
                   "cover GET, so a link or image on another site can make the signed-in user do it. Make it a POST behind the CSRF check.", {})


# ---------------------------------------------------------------- tests pointed at production

_DATABASE_URL = re.compile(r"^(?:postgres(?:ql)?|mysql|mariadb|mssql|oracle|mongodb(?:\+srv)?|rediss?|amqps?|cockroachdb)(?:\+\w+)?://[^:/@\s]+:([^@\s]+)@([^/:?\s]+)", re.I)
_PRODUCTION_HOST = re.compile(
    r"(?:^|[.-])(?:prod|production|live)(?:[.-]|\d|$)|\.rds\.amazonaws\.com$|\.cache\.amazonaws\.com$|\.docdb\.amazonaws\.com$|\.redshift\.amazonaws\.com$"
    r"|\.database\.windows\.net$|\.database\.azure\.com$|\.redis\.cache\.windows\.net$|\.mongodb\.net$|\.neon\.tech$|\.supabase\.co$|\.aivencloud\.com$"
    r"|\.cockroachlabs\.cloud$|\.psdb\.cloud$|\.upstash\.io$|\.redislabs\.com$|\.redis-cloud\.com$|\.cloudsql\.", re.I)


def _production_in_tests(tree: ast.Module) -> Iterator[tuple]:
    """A test fixture holding a password for a hosted or production database: the suite reads and changes real data, and the password is
    committed with the tests."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 500:
            found = _DATABASE_URL.match(node.value.strip())
            if found and not re.search(r"[${}<>]", found.group(1)) and _PRODUCTION_HOST.search(found.group(2)):
                yield ("live-credential-in-test", node.lineno, "A test holds credentials for what looks like a production or hosted database "
                       "(value withheld), so running the suite reads and changes real data. Point tests at a throwaway database.", {})


# ---------------------------------------------------------------- handlers that skip the scoping their siblings apply

_USER_REFERENCE = re.compile(r"\bcurrent_user\b|\brequest\.user\b|\bg\.user\b|\bself\.request\.user\b|\bget_current_user\b|\bcurrent_identity\b|\bget_jwt_identity\b"
                             r"|\buser\.(?:id|pk|organization|org|org_id|tenant|tenant_id|account|account_id|company|team)\b|\b(?:owner|user|tenant|organization|account)_id\s*=")
_SCOPED_QUERY = re.compile(r"\b([A-Z]\w*)\.(?:query|objects)\b")
_LOADS_BY_ID = re.compile(r"\b([A-Z]\w*)\.(?:query\.(?:get_or_404|get|filter_by|filter)|objects\.(?:get|filter|all|select_related|prefetch_related|only|values|iterator))\("
                          r"|\bget_object_or_404\(\s*([A-Z]\w*)\b|\bsession\.get\(\s*([A-Z]\w*)\b")
_VIEW_BASE = re.compile(r"View(?:Set)?$|APIView$|Resource$|Handler$")
_CHECKS_ACCESS = re.compile(r"permission|admin|staff|superuser|role|scope|owner|authori[sz]e|check_access|can_|allowed|ensure_|verify_", re.I)


def _handlers(tree: ast.Module) -> Iterator[tuple[ast.AST, ast.ClassDef | None]]:
    """Route functions, and the methods of view classes, each with its class."""
    for node in tree.body:
        if isinstance(node, FUNCTIONS) and any(_ROUTE.search(name) for name in _decorator_names(node)):
            yield node, None
        elif isinstance(node, ast.ClassDef) and any(_VIEW_BASE.search(_text(base)) for base in node.bases):
            for method in (item for item in node.body if isinstance(item, FUNCTIONS)):
                yield method, node


def _guarded(function: ast.AST, owner: ast.ClassDef | None) -> bool:
    """Signed-in only: a login decorator, a dependency on the current user, or a view class that requires authentication."""
    if any(re.search(r"login_required|auth|jwt_required", name) for name in _decorator_names(function)):
        return True
    if any(re.search(r"Depends\(\s*(?:get_)?current_\w*user|Security\(", _text(default)) for default in [*function.args.defaults, *function.args.kw_defaults] if default is not None):
        return True
    return owner is not None and bool(re.search(r"LoginRequired|IsAuthenticated|permission_classes|authentication_classes", _text(owner)[:4000]))


def _unscoped_lookups(tree: ast.Module) -> Iterator[tuple]:
    """In a file where one handler scopes a model to the signed-in user or tenant, another that loads it by id with no user in sight lets any
    signed-in user read or change someone else's record."""
    handlers = list(_handlers(tree))
    scoped: dict[str, str] = {}
    for function, _ in handlers:
        for statement in _walk_own(function):
            if isinstance(statement, (ast.Assign, ast.Return, ast.Expr)) and _USER_REFERENCE.search(_text(statement)):
                for model in _SCOPED_QUERY.findall(_text(statement)):
                    scoped.setdefault(model, function.name)
    if not scoped:
        return
    for function, owner in handlers:
        source = _text(function)
        decorators = " ".join(_decorator_names(function))
        if _USER_REFERENCE.search(source) or "get_queryset" in source or "get_object" in source or not _guarded(function, owner):
            continue
        if _CHECKS_ACCESS.search(decorators) or any(isinstance(call, ast.Call) and _CHECKS_ACCESS.search(_text(call.func).rsplit(".", 1)[-1])
                                                     for call in _walk_own(function)):
            continue
        for found in _LOADS_BY_ID.finditer(source):
            model = next(group for group in found.groups() if group)
            if model in scoped and scoped[model] != function.name:
                line = function.lineno + source[:found.start()].count("\n")
                yield ("unscoped-lookup", line, f"{function.name} loads {model} with no user or tenant filter, though {scoped[model]} scopes {model} to "
                       "the signed-in user, so any signed-in user can reach someone else's by id. Filter by the owner, or build on the scoped query.", {})
                break


_PERMISSION_MIXIN = re.compile(r"PermissionRequired|UserPassesTest|StaffRequired|SuperuserRequired|AdminRequired|StaffMember")
_READ_ONLY_VIEW = re.compile(r"(?:List|Detail|Template|Archive|Year|Month|Day)View$")
_WRITE_VIEW = re.compile(r"(?:Create|Update|Delete|Form)View$")


def _view_facts(node: ast.ClassDef) -> tuple[bool, bool, bool, set[str]]:
    """Whether a view class requires a permission, changes data, only reads (a list or detail view), and which models it names."""
    bases = [_text(base) for base in node.bases]
    methods = {item.name for item in node.body if isinstance(item, FUNCTIONS)}
    permission = any(_PERMISSION_MIXIN.search(base) for base in bases) or any(
        isinstance(item, ast.Assign) and any(_text(target) == "permission_required" for target in item.targets) for item in node.body)
    writes = any(_WRITE_VIEW.search(base) for base in bases) or bool(methods & {"post", "form_valid", "delete", "put", "patch"})
    reads_only = not writes and any(_READ_ONLY_VIEW.search(base) for base in bases)
    return permission, writes, reads_only, set(re.findall(r"\b([A-Z]\w+)\.objects\b", _text(node)))


def _declared_models(node: ast.ClassDef) -> set[str]:
    """`model = Refund` on a generic view."""
    return {_text(item.value) for item in node.body if isinstance(item, ast.Assign) and any(_text(target) == "model" for target in item.targets)}


def _permission_inversions(tree: ast.Module) -> Iterator[tuple]:
    """A view that changes a model with only a login, beside one that only reads it and requires a permission. Each class is read once,
    and writers are found by the models they touch, so a file of thousands of views stays linear."""
    readers, writers_of = [], {}
    for node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        permission, writes, reads_only, models = _view_facts(node)
        if permission and reads_only:
            readers.append((node, models | _declared_models(node)))
        elif writes and not permission:
            for model in models:
                writers_of.setdefault(model, []).append(node)
    reported = set()
    for reader, models in readers:
        for model in sorted(models):
            writer = next((node for node in writers_of.get(model, []) if id(node) not in reported), None)
            if writer is not None:
                reported.add(id(writer))
                yield ("missing-auth", writer.lineno, f"{writer.name} changes {model} with only a login, though {reader.name}, which only reads it, "
                       "requires a permission. Require the same permission, or record why anyone signed in may do this.", {})
                break


# ---------------------------------------------------------------- code downloaded and made runnable

_DOWNLOADS = re.compile(r"(?:^|\.)(?:urlopen|urlretrieve)$|^(?:requests|httpx)\.(?:get|request|stream)$|(?:^|\.)(?:session|client|http)\.get$")
_EXEC_BITS = re.compile(r"\bS_IX(?:USR|GRP|OTH)\b")
_CHECKS_INTEGRITY = re.compile(r"\bhashlib\b|sha256|sha512|checksum|\bdigest\b|signature|\bgpg\b|\bverify\w*\(|\bhmac\b", re.I)


def _downloads_then_runs(tree: ast.Module, text: str) -> Iterator[tuple]:
    """A script fetched from a URL and installed executable, or as a git hook, runs whatever that URL serves the next time, with no pin or
    checksum to notice a change."""
    if "chmod" not in text or _CHECKS_INTEGRITY.search(text):
        return
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    if not any(_DOWNLOADS.search(_text(node.func)) for node in calls):
        return
    for node in calls:
        name = _text(node.func)
        mode = node.args[-1] if node.args else None
        runnable = (isinstance(mode, ast.Constant) and isinstance(mode.value, int) and mode.value & 0o111) or (mode is not None and _EXEC_BITS.search(_text(mode)))
        if name.rsplit(".", 1)[-1] == "chmod" and runnable:
            yield ("unverified-download-exec", node.lineno, "This makes a downloaded file executable with no pinned version or checksum, so it runs "
                   "whatever the server sends next time. Pin the version and check a hash you recorded, or commit the file.", {})
            return


# ---------------------------------------------------------------- uploads judged by their name

_UPLOAD_SOURCE = re.compile(r"\brequest\.(?:files|FILES)\b|\bUploadFile\b")
_EXTENSION_CHECK = re.compile(r"\.rsplit\(\s*[\"']\.[\"']|\bsplitext\(|\.endswith\(\s*\(?\s*[\"']\.|\bsuffix\b|\bFileExtensionValidator\(")
# A size cap, or a look at the bytes: either means the name isn't all that was checked.
_LOOKS_FURTHER = re.compile(r"MAX_CONTENT_LENGTH|content_length|\.size\b|max_size|max_upload|MAX_UPLOAD|FILE_UPLOAD_MAX|\bimghdr\b|\bmagic\b|puremagic|filetype"
                            r"|\.verify\(|content_type|mimetype|\bImageField\b|\bvalidate_image|\bsniff", re.I)


_SERVED_DIRECTORY = re.compile(r"static_folder|STATIC_ROOT|STATICFILES|[\"'/](?:static|public|www|htdocs)\b")
# Tools that pick what to do from the bytes, whatever the name says: ImageMagick, ffmpeg, office converters, archive and workbook readers.
_READS_THE_CONTENT = re.compile(r"[\"'](?:convert|magick|identify|ffmpeg|ffprobe|soffice|libreoffice|gs|pdftotext|exiftool)[\"']|\bload_workbook\(|\bImage\.open\("
                                r"|\bZipFile\(|\btarfile\.open\(|\bextractall\(|\bread_excel\(")


def _extension_only_field(item: ast.AST, cleaned: set[str]) -> ast.Call | None:
    """`sheet = forms.FileField(validators=[FileExtensionValidator(...)])` in a form with no clean method for it, or None."""
    if not (isinstance(item, ast.Assign) and isinstance(item.value, ast.Call) and _text(item.value.func).rsplit(".", 1)[-1] == "FileField"):
        return None
    validators = next((keyword.value for keyword in item.value.keywords if keyword.arg == "validators"), None)
    names = [target.id for target in item.targets if isinstance(target, ast.Name)]
    unchecked = "clean" not in cleaned and not any(f"clean_{name}" in cleaned for name in names)
    return item.value if validators is not None and "FileExtensionValidator" in _text(validators) and unchecked else None


def _extension_only_form_fields(tree: ast.Module) -> Iterator[ast.Call]:
    for form in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        cleaned = {item.name for item in form.body if isinstance(item, FUNCTIONS)}
        yield from (field for field in (_extension_only_field(item, cleaned) for item in form.body) if field is not None)


def _upload_fate(function: ast.AST) -> tuple[ast.Call, str] | None:
    """Where a handler's saved upload goes next, when the content decides what happens there: a public folder, or a tool that reads it."""
    source = _text(function)
    served, parsed = _SERVED_DIRECTORY.search(source), _READS_THE_CONTENT.search(source)
    saves = [node for node in _walk_own(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("save", "write")]
    if not saves or not (served or parsed):
        return None
    return saves[0], "served from a public folder" if served else f"handed to {parsed.group(0).strip(chr(34) + chr(39) + '(')}, which goes by the content"


def _uploads_by_extension(tree: ast.Module, text: str) -> Iterator[tuple]:
    """An upload accepted because its name ends right, then served from a public folder or handed to a tool that goes by the content: the
    bytes decide what happens, and the name checked none of them. Saving it somewhere private with nothing reading it is left alone, since a
    size cap may be set in configuration elsewhere. A Django FileField whose only validator is FileExtensionValidator, in a form with no clean
    method for it, is the same check in a form."""
    if _LOOKS_FURTHER.search(text) or not _EXTENSION_CHECK.search(text):
        return
    field = next(_extension_only_form_fields(tree), None)
    if field is not None:
        yield ("upload-extension-only", field.lineno, "This upload is checked only by its file extension, and nothing in this form looks at "
               "its content or its size, so any bytes get through to whatever reads it. Check the content, and cap the size.", {})
        return
    for function in (function for function in _functions(tree) if _UPLOAD_SOURCE.search(_text(function))):
        found = _upload_fate(function)
        if found is not None:
            save, fate = found
            yield ("upload-extension-only", save.lineno, f"This keeps an upload accepted on its file extension alone and it's {fate}, so the bytes "
                   "decide what happens, whatever the name says. Check what the file really is first, and keep uploads outside what's served.", {})
            return


# ---------------------------------------------------------------- what a model's tool call is trusted to do

_TOOL_NAME = re.compile(r"\.function\.name\b|\b(?:tool_call|tool_use|tool|call|block|function_call|fn)\w*\.name\b|\b(?:tool_call|call|tool)\w*\[[\"']name[\"']\]")
_TOOL_INPUT = re.compile(r"\.input\[|\.input\.get\(|\.function\.arguments\b|\[[\"']arguments[\"']\]|\btool_input\b")
_VALIDATES = re.compile(r"model_validate|parse_obj|parse_raw|TypeAdapter|jsonschema|\bvalidate\w*\(|\bisinstance\(|\bint\(|\.issubset\(|\ballowed\w*\b|\bschema\b", re.I)
_DESTRUCTIVE = re.compile(r"\.delete\(|\bos\.(?:remove|unlink|rmdir)\(|\bshutil\.rmtree\(|\bsubprocess\.\w+\(|\.unlink\(")
_WRITE_SQL = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|REPLACE|MERGE)\b", re.I)


def _destroys(call: ast.Call, bound: dict) -> bool:
    """A delete, a removal, a subprocess, a write through the ORM, or SQL that writes. `execute("SELECT ...")` and `dict.update()` don't."""
    if _DESTRUCTIVE.search(_text(call.func) + "("):
        return True
    if isinstance(call.func, ast.Attribute) and call.func.attr == "execute" and call.args:
        sql = bound.get(call.args[0].id) if isinstance(call.args[0], ast.Name) else call.args[0]
        return isinstance(sql, ast.Constant) and isinstance(sql.value, str) and bool(_WRITE_SQL.match(sql.value))
    return _is_db_write(call) and isinstance(call.func, ast.Attribute) and call.func.attr == "update"


def _names_checked(function: ast.AST) -> str:
    """The text of every membership test and startswith call in a function, read once: `name in TOOLS`, `name.startswith("_")`."""
    return " ".join(_text(other) for other in _walk_own(function)
                    if (isinstance(other, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in other.ops))
                    or (isinstance(other, ast.Call) and isinstance(other.func, ast.Attribute) and other.func.attr == "startswith"))


def _unchecked_dispatch(function: ast.AST) -> tuple[ast.Call, str] | None:
    """The first `getattr(obj, <the name a model's tool call gave>)` whose name nothing checks, with that name."""
    dispatched = [node for node in _walk_own(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                  and len(node.args) >= 2 and _TOOL_NAME.search(_text(node.args[1]))]
    checked = _names_checked(function) if dispatched else ""
    return next(((node, _text(node.args[1])) for node in dispatched if _text(node.args[1]) not in checked), None)


def _names_in(node: ast.AST) -> set[str]:
    return {name.id for name in ast.walk(node) if isinstance(name, ast.Name)}


def _tool_input_names(function: ast.AST) -> set[str]:
    """Names holding values from a tool call's input, a few hops deep: `for group in call.input["groups"]: for dup_id in group["remove"]:`."""
    tainted: set[str] = set()
    for _ in range(3):
        for node in _walk_own(function):
            if isinstance(node, (ast.For, ast.AsyncFor)) and (_TOOL_INPUT.search(_text(node.iter)) or _names_in(node.iter) & tainted):
                tainted |= _names_in(node.target)
            elif isinstance(node, ast.Assign) and (_TOOL_INPUT.search(_text(node.value)) or _names_in(node.value) & tainted):
                tainted |= {name for target in node.targets for name in _names_in(target)}
    return tainted


def _unchecked_tool_effect(function: ast.AST) -> ast.Call | None:
    """The first destructive call that tool-call input reaches, in a function that validates nothing."""
    tainted = _tool_input_names(function)
    bound = {node.targets[0].id: node.value for node in _walk_own(function) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    return next((node for node in _walk_own(function) if isinstance(node, ast.Call) and _destroys(node, bound) and _names_in(node) & tainted), None)


def _tool_calls_trusted(tree: ast.Module) -> Iterator[tuple]:
    """A model's tool call is untrusted input: its name can pick any attribute, private ones included, and its arguments can name any record."""
    for function in _functions(tree):
        source = _text(function)
        dispatch = _unchecked_dispatch(function)
        if dispatch is not None:
            yield ("tool-call-unchecked", dispatch[0].lineno, f"getattr picks whatever method the model names, internal ones included. Look {dispatch[1]} "
                   "up in an explicit registry of tools, and refuse anything else.", {})
        effect = _unchecked_tool_effect(function) if _TOOL_INPUT.search(source) and not _VALIDATES.search(source) else None
        if effect is not None:
            yield ("tool-call-unchecked", effect.lineno, "Values from the model's tool call reach this destructive call unchecked. Validate them "
                   "against a schema and check each id is one you offered the model.", {})


def findings(tree: ast.Module, path: str, is_test: bool, text: str = "") -> list[tuple]:
    """(rule, line, message, overrides) for one parsed module. A rule that breaks on unusual code loses only its own findings."""
    # Each rule runs only where the module's text holds what it looks for, so a file with none of it costs a few regex scans.
    wanted = [(_production_in_tests, r"://")] if is_test else [
        (_agent_permissions, r"bypassPermissions|dangerously|approval_policy|sandbox|environ"), (_header_leaks, r"\.(?:headers|META)\b"),
        (_mass_assignment, r"setattr"), (_weak_path_checks, r"startswith"), (_state_changing_gets, r"login_required|LoginRequired"),
        (_unscoped_lookups, r"\.(?:query|objects)\b"), (_permission_inversions, _PERMISSION_MIXIN.pattern + "|permission_required"),
        (_tool_calls_trusted, r"getattr|\.input\b|arguments|tool_input")]
    rules = [lambda rule=rule: rule(tree) for rule, needs in wanted if re.search(needs, text)] if text else [lambda rule=rule: rule(tree) for rule, _ in wanted]
    if not is_test:
        rules += [lambda: _ssrf_denylists(tree, text), lambda: _downloads_then_runs(tree, text), lambda: _uploads_by_extension(tree, text)]
    found: list[tuple] = []
    for rule in rules:
        try:
            found += list(rule())
        except (RecursionError, ValueError, AttributeError, TypeError):  # occam: ignore[swallowed-exception] one rule's miss, never the file's
            continue
    return found
