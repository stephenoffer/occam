"""Python rules about what runs: control flow, exceptions, comparisons and calls."""

from __future__ import annotations

import ast
import builtins
import functools
import re

from .py_helpers import (
    NESTED_QUANTIFIER,
    COMPARED_SECRET, HTTP_MODULES, HTTP_VERBS, MIGRATION_PATH, MONEY_NAME, PLACEHOLDER_NAME, QUERY_METHODS, ROUTE_DECORATOR_NAME, SECRET_NAME, SQL_NUMBER_CALLS,
    _call_name, _chain,
    _dotted, _has_sql, _interpolated, _is_constant_none_or_empty, _is_dynamic_string, _last, _names_in,
    _is_literal, _looks_up_a_constant, _string_parts, _walk_own, builds_bind_markers, head_is_re, holds_at, is_literal_binding, looks_like_auth_check,
)

_BUILTINS = frozenset(dir(builtins))
SQL_METHODS = {"execute", "executemany", "raw", "text", "query", "executescript", "read_sql", "read_sql_query", "fetch", "fetchrow", "fetchval"}
SQL_TEXT_KEYWORDS = ("statement", "sql", "query", "stmt", "operation")
SQL_RECEIVER = re.compile(r"(?:^|[._])(?:cur|cursor|conn|connection|db|database|session|engine)\d*(?:$|[._])", re.I)
DJANGO_EXTRA_SQL = ("where", "select", "tables", "order_by")
HTTP_LIBRARIES = {"requests", "httpx", "aiohttp", "urllib3"}
HTTP_RECEIVER = re.compile(r"(?:^|[._])(?:requests?|httpx|aiohttp|urllib3|sessions?|sess|clients?|http|https|api)\d*(?:$|[._])", re.I)
HTTP_SETTING_UP = {"Session", "ClientSession", "Client", "AsyncClient"}
CREDENTIAL_ARGUMENT = re.compile(r"password|passwd|passphrase|secret|(?:^|_)pwd(?:_|$)", re.I)
MEANS_A_FOLDER = re.compile(r"cwd|dir|path|folder", re.I)  # `cwd_key(pwd)`: there, pwd is where it's working
HASHES_A_PASSWORD = re.compile(r"(?:hash|digest|encrypt|encode|store|save|set|check|verify)\w*_(?:password|passwd)|(?:password|passwd)_?(?:hash|digest)", re.I)
WEAK_HASHES = {"hashlib.md5", "hashlib.sha1", "md5", "sha1"}
# Sound digests that are still fast, so a password run through one once is cheap to guess. Fine for tokens with real entropy.
FAST_HASHES = {f"{prefix}{name}" for prefix in ("hashlib.", "") for name in
               ("sha224", "sha256", "sha384", "sha512", "sha3_224", "sha3_256", "sha3_384", "sha3_512", "blake2b", "blake2s")}
PASSWORD_ARGUMENT = re.compile(r"password|passwd|passphrase|(?:^|_)pwd(?:_|$)", re.I)
# `sha256(user.password_hash)` derives something from a stored hash, and `sha256(password_reset_token)` stores a random token as it should.
ALREADY_HASHED = re.compile(r"hash|digest|token|nonce|otp|reset|code|salt", re.I)
SLOW_KDF = re.compile(r"pbkdf2|scrypt|bcrypt|argon2|hashpw|make_password|generate_password_hash|passlib|CryptContext", re.I)
# What a token made by hashing has to contain to be unguessable: a secret, or randomness. A clock, an id or an email isn't either.
SECRET_MATERIAL = re.compile(r"secret|key|salt|pepper|nonce|urandom|token|random|randbits|uuid4|SystemRandom", re.I)
GUESSABLE_PART = re.compile(r"\btime\.time(?:_ns)?\(|\b(?:datetime\.)?(?:now|utcnow|today)\(|\bid\b|\.(?:id|pk|email|username)\b|\b(?:email|username|user_id)\b")
RANDOM_CALLS = {"random", "randint", "choice", "choices", "randrange", "sample", "getrandbits"}
CODE_LOADERS = {"pickle.load", "pickle.loads", "cPickle.loads", "cPickle.load", "marshal.loads", "marshal.load", "dill.load", "dill.loads", "shelve.open"}
ARRAY_GROWERS = {"pd.concat", "pandas.concat", "np.append", "numpy.append", "np.concatenate", "numpy.concatenate", "np.vstack", "np.hstack", "numpy.vstack", "numpy.hstack"}
TASK_STARTERS = {"asyncio.create_task", "asyncio.ensure_future", "threading.Thread", "Thread"}
BOUNDING_WORDS = re.compile(r"semaphore|boundedsemaphore|taskgroup|queue", re.I)
DATA_RECEIVER = re.compile(r"(?:^|\.)(?:store|repo|repository|dao|db|database|crud|storage|gateway)$")
DATA_READ = re.compile(r"(?:get|find|fetch|load|list|lookup|query|read)(?:_|$)")


def _always_true_operand(test: ast.AST) -> bool:
    return (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or)
            and any(isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value for value in test.values))


def check_constant_condition(ctx, node) -> None:
    test = node.test
    if _always_true_operand(test):
        ctx.add("always-true-condition", node, "A non-empty string on one side of 'or' makes this condition always true.")
    if isinstance(test, ast.Constant) and not test.value:
        ctx.add("dead-branch", node, "This condition is always false.")
    elif isinstance(node, ast.If) and isinstance(test, ast.Constant) and test.value:
        ctx.add("dead-branch", node, "This condition is always true.")


def _only_reraises(handler: ast.ExceptHandler) -> bool:
    if len(handler.body) != 1 or not isinstance(handler.body[0], ast.Raise) or handler.body[0].cause is not None:
        return False
    raised = handler.body[0].exc
    return raised is None or (isinstance(raised, ast.Name) and raised.id == handler.name)


_LINTER_DIRECTIVE = re.compile(r"\bnoqa(?::\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)?|\btype:\s*ignore(?:\[[^\]]*\])?|\bpylint:\s*disable=\S+|\bnosec\b(?:\s+[A-Z]\d+)?|\bpragma:\s*no\s*cover", re.I)


def _states_a_reason(ctx, lines: list[int]) -> bool:
    """A sentence, as opposed to a bare instruction to a linter, which only shows someone silenced the warning."""
    source = ctx.text.split("\n")
    return any(len(re.findall(r"[A-Za-z']{2,}", _LINTER_DIRECTIVE.sub("", source[line - 1].split("#", 1)[-1]))) >= 3 for line in lines)


def check_try(ctx, node, function) -> None:
    # Every handler has to qualify: `except KeyError: raise` ahead of a broader handler that does real work is deliberate.
    if node.handlers and not ctx.is_test and all(_only_reraises(handler) for handler in node.handlers):
        ctx.add("useless-except", node.handlers[0], "This handler only re-raises what it caught.")
    for handler in node.handlers:
        caught = _last(_dotted(handler.type)) if handler.type is not None else None
        broad = caught in (None, "Exception", "BaseException")
        if handler.type is None and not ctx.is_test:
            ctx.add("bare-except", handler)
        if function is not None and looks_like_auth_check(function):
            for statement in handler.body:
                if isinstance(statement, ast.Return) and isinstance(statement.value, ast.Constant) and statement.value.value is True:
                    ctx.add("fail-open", statement, f"{function.name} returns True when its check errors.")
        if not ctx.is_test:
            _check_unverified_fallback(ctx, handler)
        if not broad or ctx.is_test:
            continue
        if _drops_error(handler):
            comments = [line for line in range(handler.lineno, (handler.end_lineno or handler.lineno) + 1) if line in ctx.comment_lines]
            confidence = ("low" if _states_a_reason(ctx, comments) else "medium") if comments else None
            ctx.add("swallowed-exception", handler, f"except {caught or ''} drops the error.".replace("  ", " "), **({"confidence": confidence} if confidence else {}))


def _check_unverified_fallback(ctx, handler: ast.ExceptHandler) -> None:
    """An error path that decodes the token unverified and carries on. Reported on the handler, not the decode, which jwt-unverified already
    names, and as a lead: whether the claims then grant anything is beyond this."""
    unverified = any(isinstance(call, ast.Call) and _decodes_unverified(call) for statement in handler.body for call in ast.walk(statement))
    if unverified and not _denies(handler.body):
        ctx.add("fail-open", handler, "When verification fails with this error, the handler decodes the token without checking its signature and "
                                      "carries on, so a forged token is accepted for as long as the error lasts. Deny instead.", confidence="medium")


_DENIES = re.compile(r"(?:^|\.)(?:abort|HTTPException|PermissionDenied|Unauthorized|Forbidden|AuthenticationFailed|NotAuthenticated|HttpResponseForbidden)$")


def _denies(statements: list) -> bool:
    """The handler ends in a refusal: it raises, aborts, or returns nothing, False, or an error. Reading unverified claims to log them is fine then."""
    for node in (inner for statement in statements for inner in ast.walk(statement)):
        if isinstance(node, ast.Raise) or (isinstance(node, ast.Call) and _DENIES.search(_dotted(node.func) or "")):
            return True
    last = statements[-1] if statements else None
    return isinstance(last, ast.Return) and (last.value is None or (isinstance(last.value, ast.Constant) and last.value.value in (None, False)))


def _decodes_unverified(call: ast.Call) -> bool:
    """A `jwt.decode` that turns signature checking off, through its options or its verify argument, on one line: only what jwt-unverified
    already reports, since gate blocks on fail-open at any confidence and this mustn't add a block or a send-back of its own."""
    if _call_name(call) not in ("jwt.decode", "decode") or "jwt" not in _dotted(call.func).lower():
        return False
    for keyword in call.keywords:
        if keyword.arg == "verify" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False and keyword.value.lineno == call.lineno:
            return True
        if keyword.arg == "options" and isinstance(keyword.value, ast.Dict):
            for key, value in zip(keyword.value.keys, keyword.value.values):
                if isinstance(key, ast.Constant) and key.value == "verify_signature" and isinstance(value, ast.Constant) and value.value is False:
                    return True
    return False


def _logs_at_debug(statement: ast.AST) -> bool:
    return isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and _last(_call_name(statement.value)) in ("debug", "trace")


def _drops_error(handler: ast.ExceptHandler) -> bool:
    if not handler.body:
        return True
    for statement in handler.body:
        if isinstance(statement, (ast.Pass, ast.Continue, ast.Break)) or _logs_at_debug(statement):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        if isinstance(statement, ast.Return) and _is_constant_none_or_empty(statement.value):
            continue
        return False
    return True


def check_loop(ctx, node, loops, function) -> None:
    if loops >= 2:
        ctx.add("nested-loops", node, f"Loop nesting depth {loops + 1}.")
    if isinstance(node, (ast.For, ast.AsyncFor)) and function is not None:
        outer = ast.dump(node.iter)
        for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(child, (ast.For, ast.AsyncFor)) and child is not node and ast.dump(child.iter) == outer and isinstance(node.iter, (ast.Name, ast.Attribute)):
                ctx.add("nested-same-collection", child, f"Nested loop over {_dotted(node.iter)} again.")
                break
        _csv_split(ctx, node)
    if isinstance(node, (ast.For, ast.AsyncFor)) and _is_index_loop(node.iter) and ctx.imports_numeric:  # at module level too, where notebook cells and scripts loop
        frame = _row_by_position(node)
        if frame:
            ctx.add("dataframe-iterrows", node, f"Reads {frame} one row at a time by position.")
        else:
            ctx.add("python-loop-over-array", node, "Python index loop in a module that uses numeric arrays.")
    handles_error_with_sleep = False
    for child in node.body:
        if isinstance(child, ast.Try):
            for handler in child.handlers:
                if any(isinstance(n, ast.Call) and _last(_call_name(n)) == "sleep" for s in handler.body for n in ast.walk(s)):
                    handles_error_with_sleep = True
    if handles_error_with_sleep:
        ctx.add("handrolled-retry", node, "A loop that catches and sleeps is a hand-written retry.")


def _row_by_position(loop: ast.For) -> str | None:
    """`df.iloc[i]` with `i` from `range(len(df))`: the frame read that way, or None."""
    index = loop.target.id if isinstance(loop.target, ast.Name) else None
    for child in ast.walk(ast.Module(body=loop.body, type_ignores=[])):
        if (index and isinstance(child, ast.Subscript) and isinstance(child.value, ast.Attribute) and child.value.attr in ("iloc", "loc", "iat", "at")
                and isinstance(child.slice, ast.Name) and child.slice.id == index):
            return _dotted(child.value.value) or "a frame"
    return None


def _is_index_loop(iterable: ast.AST) -> bool:
    if not (isinstance(iterable, ast.Call) and _call_name(iterable) == "range" and iterable.args):
        return False
    last = iterable.args[-1]
    return (isinstance(last, ast.Call) and _call_name(last) == "len") or (isinstance(last, ast.Subscript) and "shape" in ast.dump(last))


def _csv_split(ctx, node) -> None:
    target = node.target.id if isinstance(node.target, ast.Name) else ""
    if target not in ("line", "row", "l", "record", "rec"):
        return
    for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "split" and inner.args \
                and isinstance(inner.args[0], ast.Constant) and inner.args[0].value == ",":
            ctx.add("handrolled-csv", inner, "Splitting on commas breaks on quoted fields.")
            return


# An access check names a user, a request or a permission predicate, which a lock's `self._owner` doesn't.
_AUTH_WORD = re.compile(r"\b(?:is_(?:admin|staff|superuser|authenticated|authorized)|has_perms?|has_permissions?|has_roles?)\b"
                        r"|\b(?:current_)?user\w*\.(?:roles?|permissions?|perms?|tenant\w*)\b|\brequest\.user\b"
                        r"|\b(?:owner|tenant|account)_id\b.{0,80}\b(?:current_)?user\b|\b(?:current_)?user\b.{0,80}\b(?:owner|tenant|account)_id\b", re.I)


_REQUEST_STATE = re.compile(r"\brequest\.(?:args|form|json|data|values|files|headers|cookies|GET|POST|method|user|query_params|body|get_json)\b|\bcurrent_user\b|\bg\.user\b")


def _serves_requests(function) -> bool:
    """A route handler, or what a framework calls per request: a FastAPI dependency, which takes others through Depends()."""
    decorated = [_dotted(decorator.func if isinstance(decorator, ast.Call) else decorator) for decorator in function.decorator_list]
    if any(ROUTE_DECORATOR_NAME.search(name) for name in decorated if name):
        return True
    defaults = [*function.args.defaults, *(d for d in function.args.kw_defaults if d is not None)]
    return any(isinstance(default, ast.Call) and _last(_call_name(default)) in ("Depends", "Security") for default in defaults)


def _narrows_a_type(test: ast.AST) -> bool:
    """`assert x is not None` and `assert isinstance(...)` tell a type checker something. They check no input."""
    if isinstance(test, ast.Call) and _call_name(test) == "isinstance":
        return True
    return isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.IsNot) and _is_constant_none_or_empty(test.comparators[0])


def check_assert(ctx, node, function) -> None:
    is_type_check = isinstance(node.test, ast.Call) and _call_name(node.test) == "isinstance"
    if not is_type_check and _AUTH_WORD.search(ast.unparse(node.test)):
        # Access checks are the costly case: run with -O and the check is gone while everything else still works.
        ctx.add("assert-validation", node, "This access check is an assert, so python -O removes it and lets everyone through. Raise or deny instead.", severity="high", confidence="medium")
        return
    if not _narrows_a_type(node.test) and (_serves_requests(function) or _REQUEST_STATE.search(ast.unparse(node.test))):
        ctx.add("assert-validation", node, "This asserts something about a request, its input or its user, and python -O removes asserts, so the check is gone "
                                           "in an optimized deployment. Raise or return an error instead.", severity="high", confidence="medium")
        return
    params = {arg.arg for arg in function.args.args + function.args.kwonlyargs}
    if not function.name.startswith("_") and _names_in(node.test) & params:
        ctx.add("assert-validation", node, "This check disappears under python -O.")


def check_raise(ctx, node) -> None:
    if not isinstance(node.exc, ast.Call):
        return
    name = _call_name(node.exc)
    if name in ("Exception", "BaseException"):
        ctx.add("generic-exception", node, f"raise {name}(...)")
    if node.exc.args and isinstance(node.exc.args[0], ast.Constant) and isinstance(node.exc.args[0].value, str) and len(node.exc.args) == 1:
        if re.fullmatch(r"(?:invalid|bad|wrong|failed|error|an? error occurred|something went wrong)[\w ]{0,20}\.?", node.exc.args[0].value.strip(), re.I):
            ctx.add("opaque-error", node, f"'{node.exc.args[0].value}' doesn't say what was wrong.")


def check_string_concat(ctx, node, function) -> None:
    name = node.target.id
    for other in _walk_own(function):
        if isinstance(other, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in other.targets) \
                and isinstance(other.value, ast.Constant) and isinstance(other.value.value, str):
            ctx.add("string-concat-loop", node, f"{name} grows by concatenation in a loop.")
            return


def note_attribute(ctx, node: ast.Attribute) -> None:
    dotted = _dotted(node)
    if not dotted:
        return
    head = dotted.split(".")[0]
    module = ctx.module_aliases.get(head)
    if module:
        ctx.attr_uses.append({"module": module, "head": head, "chain": dotted.split(".")[1:], "line": node.lineno, "guarded": dotted.split(".")[-1] in ctx.code_strings})


def _final_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _final_name(node.func)
    if isinstance(node, ast.Subscript):
        return str(node.slice.value) if isinstance(node.slice, ast.Constant) else _final_name(node.value)
    return node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ""


def _compares_a_secret(sides: tuple) -> bool:
    """By what each side is called, not by everything it mentions, since `vault_secrets.c.id` is a column. A style_signature is a cache key."""
    names = [_final_name(side) for side in sides]
    if any(name.lower().endswith("signature") and not COMPARED_SECRET.search(name) for name in names):
        return False
    return any(COMPARED_SECRET.search(name) for name in names) or any("hmac" in name.lower() for side in sides for name in _names_of(side))


def check_compare(ctx, node: ast.Compare, loops: int, function: ast.AST | None) -> None:
    if len(node.ops) != 1:
        return
    right = node.comparators[0]
    if loops and function is not None and isinstance(node.ops[0], (ast.In, ast.NotIn)) and isinstance(right, ast.Name) and _is_local_list(right.id, function):
        ctx.add("list-membership-in-loop", node, f"'in' on the list {right.id} is linear, so this loop is quadratic.")
    if not ctx.is_test and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
        both = (node.left, right)
        if not any(isinstance(side, ast.Constant) for side in both) and _compares_a_secret(both):
            ctx.add("secret-compare", node, "A secret compared with == can leak through timing.")


def check_format_string(ctx, node: ast.JoinedStr) -> None:
    constant = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    dynamic = any(isinstance(v, ast.FormattedValue) for v in node.values)
    if not dynamic:
        return
    if re.search(r"https?://[^\s]*\?[^\s]*=", constant) or re.search(r"\?\w+=[^=]*&\w+=", constant):
        ctx.add("handrolled-url", node, "Query string built by formatting, so the values aren't encoded.")
    elif re.match(r"\s*\{\s*\"\w+\"\s*:", constant):
        ctx.add("handrolled-json", node, "JSON built by formatting, so the values aren't escaped.")


def check_string_join(ctx, node: ast.BinOp) -> None:
    """JSON glued together with +, as check_format_string reads it from an f-string. Once per chain, and a value through json.dumps is escaped."""
    if not isinstance(node.op, ast.Add) or getattr(node, "_occam_inner_join", False):
        return
    pieces, inner = [], node
    while isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.Add):
        inner._occam_inner_join = True
        pieces.append(inner.right)
        inner = inner.left
    pieces.append(inner)
    first = pieces[-1]
    values = [piece for piece in pieces if not isinstance(piece, ast.Constant)]
    if (isinstance(first, ast.Constant) and isinstance(first.value, str) and re.match(r"\s*\{\s*\"\w+\"\s*:", first.value)
            and values and not all(isinstance(value, ast.Call) and _call_name(value).endswith("dumps") for value in values)):
        ctx.add("handrolled-json", node, "JSON built by joining strings, so the values aren't escaped.")


def check_call(ctx, node: ast.Call, statement: ast.AST, loops: int, function: ast.AST | None) -> None:
    name = _call_name(node)
    if isinstance(function, ast.AsyncFunctionDef) and isinstance(statement, ast.Expr) and statement.value is node and (name in ("asyncio.sleep", "asyncio.gather", "asyncio.wait_for") or name in ctx.async_names):
        ctx.add("missing-await", node, f"{name}() is a coroutine, and nothing awaits it.")
    last = _last(name)
    head = name.split(".")[0] if name else ""
    keywords = {k.arg: k.value for k in node.keywords}
    in_async = isinstance(function, ast.AsyncFunctionDef)
    if not ctx.is_test:
        _security_call(ctx, node, name, last, head, keywords, statement, function)
        _practice_call(ctx, node, name, last, head, keywords, statement)
    if name == "print":
        ctx.prints.append(node.lineno)
    if last == "iterrows":
        ctx.add("dataframe-iterrows", node)
    if in_async and (name in ("time.sleep", "urllib.request.urlopen", "urlopen", "subprocess.run", "subprocess.call", "subprocess.check_output", "os.system")
                     or (head in ("requests",) and last in HTTP_VERBS)):
        ctx.add("blocking-in-async", node, f"{name}() blocks the event loop.")
    if not ctx.is_test and head in HTTP_MODULES - {"httpx"} and last in HTTP_VERBS and "timeout" not in keywords:
        ctx.add("missing-timeout", node, f"{name}() waits forever by default.")
    elif not ctx.is_test and last == "urlopen" and "timeout" not in keywords and len(node.args) < 3:
        ctx.add("missing-timeout", node, f"{name}() has no timeout.")
    if loops:
        _in_loop(ctx, node, name, last, head, function)
    if not ctx.is_test:
        _gather(ctx, node, name, last, function)
        if function is not None and name and _is_remote_call(name, last, head):
            ctx.remote_defs.add((function.name, function.lineno))
        if loops and name and "." not in name and name not in _BUILTINS and not (ctx.is_script or MIGRATION_PATH.search(ctx.path)):
            ctx.loop_calls.append([name, node.lineno])
        _materialize(ctx, node, name, last, keywords)
        _reinvented(ctx, node, name, last, keywords, statement)


def _security_call(ctx, node, name, last, head, keywords, statement, function) -> None:
    first = node.args[0] if node.args else None
    _command_execution(ctx, node, name, head, keywords, first, function)
    _regex_literal(ctx, node, name, first)
    _deserialization(ctx, node, name, keywords)
    _sql_call(ctx, node, keywords, statement, function)
    _tls_disabled(ctx, node, head, keywords)
    if name in WEAK_HASHES and not (keywords.get("usedforsecurity") and getattr(keywords["usedforsecurity"], "value", True) is False):
        if _hashes_a_credential(node, statement, function):
            ctx.add("weak-password-hash", node, f"{name}() on a password or secret.")
        else:
            ctx.add("weak-crypto", node, f"{name}() in use.")
    elif (name in FAST_HASHES or (name == "hashlib.new" and first is not None)) and _hashes_a_password(node, function):
        # A lead rather than a stop: the digest itself is sound, and the same call on a random token is right.
        ctx.add("weak-password-hash", node, f"{name}() on a password is fast to brute-force, salted or not. Use argon2, scrypt or bcrypt.", confidence="medium")
    if head == "random" and last in RANDOM_CALLS and _targets_secret(statement, function):
        ctx.add("insecure-random", node, f"{name}() isn't safe for secrets.")
    if name in ("uuid.uuid1", "uuid1") and _targets_secret(statement, function):
        ctx.add("insecure-random", node, "uuid1() is built from the clock and the host's MAC address, so nearby values are guessable. Use secrets.token_urlsafe().")
    if head == "hashlib" and _hashes_only_guessable(ctx, node, statement, function):
        ctx.add("insecure-random", node, "This token is a hash of values someone else can know or guess, such as an id, an email or the time, and hashing "
                                         "doesn't make them secret. Use secrets.token_urlsafe().")
    if name == "tempfile.mktemp":
        ctx.add("insecure-tempfile", node)
    if name == "os.chmod" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 0o777:
        ctx.add("world-writable", node)


def _hashes_a_credential(node: ast.Call, statement: ast.AST, function: ast.AST | None) -> bool:
    """What's being hashed says so, and not what's near it: fingerprint_secret_line(line) hashes a line. A name that says it hashes a password is the exception, in `def hash_password(p):`."""
    given = [*node.args, *(keyword.value for keyword in node.keywords)]
    names = []
    for child in (inner for argument in given for inner in ast.walk(argument)):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
        elif isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Constant):
            names.append(str(child.slice.value))
    if any(CREDENTIAL_ARGUMENT.search(name) and not (name.lower() == "pwd" and function is not None and MEANS_A_FOLDER.search(function.name)) for name in names):
        return True
    targets = [target.id for target in getattr(statement, "targets", []) if isinstance(target, ast.Name)]
    return any(HASHES_A_PASSWORD.search(name) for name in [*targets, *([function.name] if function is not None else [])])


def _argument_names(node: ast.Call) -> list[str]:
    names = []
    for child in (inner for argument in [*node.args, *(keyword.value for keyword in node.keywords)] for inner in ast.walk(argument)):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
        elif isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Constant):
            names.append(str(child.slice.value))
    return names


def _hashes_a_password(node: ast.Call, function: ast.AST | None) -> bool:
    """A fast digest of a password, by what's hashed, or in `def hash_password(p):` by its own parameter. A function that also uses a slow
    KDF is pre-hashing for it, as bcrypt's 72-byte limit makes people do, and `sha256(os.urandom(32))` there makes a salt."""
    if function is not None and SLOW_KDF.search(ast.unparse(function)):
        return False
    names = _argument_names(node)
    if any(PASSWORD_ARGUMENT.search(name) and not ALREADY_HASHED.search(name) for name in names):
        return True
    if function is None or not HASHES_A_PASSWORD.search(function.name):
        return False
    parameters = {arg.arg for arg in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]} - {"self", "cls"}
    return bool(parameters & set(names))


_TOKEN_TARGET = re.compile(r"token|nonce|otp|session_?id|csrf|api_?key|secret|(?:reset|invite|invitation|verification|verify|confirm|magic)_?(?:code|key|link|id)", re.I)
_NOT_A_TOKEN = re.compile(r"cache|etag|fingerprint|checksum|lookup", re.I)  # `make_reset_cache_key` names where to look, not a secret


def _hashes_only_guessable(ctx, node: ast.Call, statement: ast.AST, function: ast.AST | None) -> bool:
    """`token = md5(f"{user.id}:{email}:{time.time()}")`: what's hashed, and what the names in it were set to, holds no secret or randomness."""
    if isinstance(statement, ast.Assign):
        targets = [ast.unparse(target) for target in statement.targets]
    elif isinstance(statement, ast.Return) and function is not None:
        targets = [function.name]
    else:
        return False
    if not any(_TOKEN_TARGET.search(target) and not _NOT_A_TOKEN.search(target) for target in targets) or not node.args:
        return False
    hashed = node.args[1:] if _call_name(node) == "hashlib.new" else node.args
    parts = [ast.unparse(argument) for argument in hashed]
    for name in {inner.id for argument in hashed for inner in ast.walk(argument) if isinstance(inner, ast.Name)}:
        for binding in (ctx.bindings(function).get(name, []) if function is not None else []):
            parts.append(ast.unparse(binding.value) if binding.value is not None else name)
    text = " ".join(parts)
    return bool(GUESSABLE_PART.search(text)) and not SECRET_MATERIAL.search(text)


def _tls_disabled(ctx, node: ast.Call, head: str, keywords: dict) -> None:
    """`verify=False` is a keyword many things take, so what's receiving it has to be talking HTTP. `repo.commit("x", verify=False)` isn't."""
    verify = keywords.get("verify")
    if not (isinstance(verify, ast.Constant) and verify.value is False):
        return
    chain = _chain(node.func)
    module = ctx.module_aliases.get(head, head).split(".")[0]
    if _last(chain) in HTTP_VERBS or _last(chain) in HTTP_SETTING_UP or module in HTTP_LIBRARIES or HTTP_RECEIVER.search(chain):
        ctx.add("tls-disabled", node)


def _is_only_written_out(ctx, name: str, function: ast.AST | None, upper: bool = False) -> bool:
    """Every binding of this name that this code could read takes a value written in the code."""
    key = (id(function), name, upper)
    if key not in ctx.name_verdicts:  # a file can bind one name thousands of times, and ask about it as often
        bindings = (ctx.bindings(function).get(name) if function is not None else None) or ctx.bindings(None).get(name)
        ctx.name_verdicts[key] = bool(bindings) and name not in ctx.declared_global() and all(is_literal_binding(binding, upper) for binding in bindings)
    return ctx.name_verdicts[key]


def _name_is_safe_in_sql(ctx, name: str, function: ast.AST | None, comprehensions: dict[str, bool]) -> bool:
    if name in comprehensions:
        return comprehensions[name]
    local = ctx.bindings(function).get(name) if function is not None else None
    if PLACEHOLDER_NAME.fullmatch(name):  # the name is a claim, so whatever sets it has to back that up. A parameter has only the name to go on.
        key = (id(function), name, "markers")
        if key not in ctx.name_verdicts:
            bindings = local or ctx.bindings(None).get(name) or []
            ctx.name_verdicts[key] = all(isinstance(binding.node, ast.arg) or (binding.value is not None and builds_bind_markers(binding.value)) for binding in bindings)
        return ctx.name_verdicts[key]
    if name.isupper() and not local:  # a constant from this module, or imported from another
        return True
    return _is_only_written_out(ctx, name, function, upper=True)


def _is_safe_in_sql(ctx, expression: ast.AST, function: ast.AST | None, comprehensions: dict[str, bool]) -> bool:
    if isinstance(expression, ast.Constant):
        return True
    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name):
        if expression.func.id in SQL_NUMBER_CALLS:
            return True
        if expression.func.id == "str" and expression.args:
            return _is_safe_in_sql(ctx, expression.args[0], function, comprehensions)
    if builds_bind_markers(expression) or _looks_up_a_constant(expression):
        return True
    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute) and expression.func.attr == "join" \
            and isinstance(expression.func.value, ast.Constant) and len(expression.args) == 1 and isinstance(expression.args[0], ast.Name):
        return _holds_only_written_out_pieces(ctx, expression.args[0].id, function)
    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name) and expression.func.id in ctx.top_names:
        return _returns_safe_sql(ctx, expression.func.id)
    names = _names_in(expression)
    return bool(names) and all(_name_is_safe_in_sql(ctx, name, function, comprehensions) for name in names)


def _holds_only_written_out_pieces(ctx, name: str, function: ast.AST | None) -> bool:
    """`where = ["a = :a"]`, grown only by `where.append("b = :b")`, then joined: every piece of the clause is written in the code."""
    bindings = ctx.bindings(function).get(name) if function is not None else None
    if not bindings or name in ctx.declared_global():
        return False
    for binding in bindings:
        if not (isinstance(binding.node, (ast.Assign, ast.AugAssign)) and isinstance(binding.value, (ast.List, ast.Tuple))
                and all(_is_literal(item, True) for item in binding.value.elts)):
            return False
    for call in _walk_own(function):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == name:
            added = call.args[-1:] if call.func.attr in ("append", "insert") else call.args[:1] if call.func.attr == "extend" else []
            for item in added:
                pieces = item.elts if call.func.attr == "extend" and isinstance(item, (ast.List, ast.Tuple)) else [item] if call.func.attr != "extend" else [None]
                if not all(_is_literal(piece, True) for piece in pieces):
                    return False
    return True


def _returns_safe_sql(ctx, name: str) -> bool:
    """A helper in this module that builds a clause, such as `ORDER BY {column}` from an allow-list: safe when every return is, read in its own scope."""
    key = ("returns-safe-sql", name)
    depth = ctx.name_verdicts.get("returns-safe-sql-depth", 0)
    if key not in ctx.name_verdicts:
        if depth >= 3:  # helpers calling helpers: three deep is as far as this reads, so a long chain stays a lead
            return False
        ctx.name_verdicts[key] = False  # a helper that calls itself isn't trusted
        ctx.name_verdicts["returns-safe-sql-depth"] = depth + 1
        try:
            helpers = [node for node in ctx.tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
            returns = [node for node in _walk_own(helpers[0]) if isinstance(node, ast.Return)] if len(helpers) == 1 else []
            ctx.name_verdicts[key] = bool(returns) and all(
                node.value is not None and all(_is_safe_in_sql(ctx, part, helpers[0], {}) for part in _interpolated(node.value)) for node in returns)
        finally:
            ctx.name_verdicts["returns-safe-sql-depth"] = depth
    return ctx.name_verdicts[key]


def _sql_call(ctx, node: ast.Call, keywords: dict, statement: ast.AST, function: ast.AST | None) -> None:
    chain = _chain(node.func)
    method = _last(chain)
    if method not in SQL_METHODS and method != "extra":
        return
    comprehensions = ctx.comprehensions_in(statement).get(id(node), {})

    def is_safe(text: ast.AST) -> bool:
        return all(_is_safe_in_sql(ctx, part, function, comprehensions) for part in _interpolated(text))

    if method == "extra":
        if any(item is not None and _is_dynamic_string(item) and not is_safe(item) for item in _django_extra_items(keywords)):
            ctx.add("sql-injection", node, f"{chain}() receives SQL built from runtime values.")
        return
    text = node.args[0] if node.args else next((keywords[key] for key in SQL_TEXT_KEYWORDS if key in keywords), None)
    if isinstance(text, ast.Name):
        _sql_held_by_name(ctx, node, chain, text.id, function, is_safe)
    elif text is not None and _is_dynamic_string(text) and _reads_as_sql(text, method, chain) and not is_safe(text):
        # Values are bound as well, so what's interpolated may only be structure, such as a checked column name.
        overrides = {"confidence": "low"} if MIGRATION_PATH.search(ctx.path) else {"confidence": "medium"} if len(node.args) > 1 else {}
        ctx.add("sql-injection", node, f"{chain}() receives SQL built from runtime values.", **overrides)


def _django_extra_items(keywords: dict) -> list:
    written = []
    for key in DJANGO_EXTRA_SQL:
        value = keywords.get(key)
        written += value.values if isinstance(value, ast.Dict) else getattr(value, "elts", [])
    return written


def _reads_as_sql(text: ast.AST, method: str, chain: str) -> bool:
    """execute() also runs shell commands and jobs, so it needs its text or its receiver to say this is SQL."""
    return _has_sql(_string_parts(text)) or (method == "execute" and bool(SQL_RECEIVER.search(chain.rpartition(".")[0])))


def _sql_held_by_name(ctx, node: ast.Call, chain: str, name: str, function: ast.AST | None, is_safe) -> None:
    """A step removed from the call, so this is a lead to read and not one to interrupt for."""
    held = holds_at(ctx.bindings(function).get(name, []), node)
    built = [value for index, value in enumerate(held) if _is_dynamic_string(value) or (index and not isinstance(value, ast.Constant))]
    if built and _has_sql(" ".join(_string_parts(value) for value in held)) and not all(is_safe(value) for value in built):
        ctx.add("sql-injection", node, f"{chain}() receives SQL built from runtime values, by way of {name}.", confidence="low" if MIGRATION_PATH.search(ctx.path) else "medium")


def _regex_literal(ctx, node, name, first) -> None:
    if name.split(".")[0] in ("re", "regex") and isinstance(first, ast.Constant) and isinstance(first.value, str) and _ambiguous_repeat(first.value):
        ctx.add("redos-regex", node, "This pattern has a repeated group containing a repeat.")


# A separator opening each pass: a character class of non-word characters, an escaped character, or a plain non-word one.
_SEPARATOR = re.compile(r"(?:\[([^\]\w\\^]+)\]|\\([^\w\s])|([^\w\s\\.\[(|^$?*+{)]))(?![?*+{])")

_CLASSES_AND_ESCAPES = re.compile(r"\\.|\[(?:\\.|[^\]\\])*\]")  # `\|` and `[|]` aren't alternatives


def _ambiguous_repeat(pattern: str) -> bool:
    """A repeated group with a repeat inside can split one string many ways, unless each pass opens with a separator the rest can't match, as `(?:[-:]\\d+)*`."""
    for match in NESTED_QUANTIFIER.finditer(pattern):
        body = match.group(0)[1:-2]
        body = body[2:] if body.startswith("?:") else body
        lead = _SEPARATOR.match(body)
        rest = body[lead.end():] if lead else ""
        if not lead or "|" in _CLASSES_AND_ESCAPES.sub("", body) or any(character in rest for character in "".join(part or "" for part in lead.groups())) or re.search(r"\.|\[\^|\\[WSD]", rest):
            return True
    return False


def _command_execution(ctx, node, name, head, keywords, first, function) -> None:
    if first is None or isinstance(first, ast.Constant):
        return
    if name in ("eval", "exec"):
        ctx.add("dynamic-eval", node, f"{name}() on a value computed at runtime.")
    if isinstance(first, ast.Name) and _is_only_written_out(ctx, first.id, function):  # `cmd = "git log"`, which is a shell command and no injection
        return
    if _shell_quoted(ctx, first, function):
        return
    shell = keywords.get("shell")
    if head == "subprocess" and isinstance(shell, ast.Constant) and shell.value is True:
        ctx.add("shell-injection", node, f"{name}(shell=True) with a value computed at runtime.")
    elif name in ("os.system", "os.popen"):
        ctx.add("shell-injection", node, f"{name}() with a value computed at runtime.")


_SHELL_QUOTERS = {"shlex.quote", "pipes.quote", "shlex.join"}


def _is_shell_quoter(ctx, func: ast.AST, function: ast.AST | None) -> bool:
    """`shlex.quote`, or a name for it: `from shlex import quote`, or `q = shlex.quote` in this function or module."""
    name = _dotted(func)
    if name in _SHELL_QUOTERS or ctx.module_aliases.get(name) in _SHELL_QUOTERS:
        return True
    if not isinstance(func, ast.Name):
        return False
    bindings = (ctx.bindings(function).get(func.id) if function is not None else None) or ctx.bindings(None).get(func.id) or []
    return bool(bindings) and all(binding.value is not None and _dotted(binding.value) in _SHELL_QUOTERS for binding in bindings)


def _quoted_for_the_shell(ctx, part: ast.AST, function: ast.AST | None) -> bool:
    if isinstance(part, ast.Constant) or (isinstance(part, ast.Call) and _dotted(part.func) in SQL_NUMBER_CALLS):
        return True
    if isinstance(part, ast.Call) and _is_shell_quoter(ctx, part.func, function):
        return True
    joined = isinstance(part, ast.Call) and isinstance(part.func, ast.Attribute) and part.func.attr == "join" and isinstance(part.func.value, ast.Constant)
    if joined and len(part.args) == 1 and isinstance(part.args[0], (ast.GeneratorExp, ast.ListComp)):
        return _quoted_for_the_shell(ctx, part.args[0].elt, function)
    return False


def _shell_quoted(ctx, command: ast.AST, function: ast.AST | None, seen: frozenset = frozenset()) -> bool:
    """A command string whose every runtime piece went through shlex.quote, directly or by way of the name holding it. A name met again,
    as in `a = b` on one branch and `b = a` on the other, proves nothing."""
    if isinstance(command, ast.Name):
        if command.id in seen:
            return False
        bindings = ctx.bindings(function).get(command.id) if function is not None else None
        values = [binding.value for binding in bindings or []]
        return bool(values) and all(value is not None and _shell_quoted(ctx, value, function, seen | {command.id}) for value in values)
    if _is_dynamic_string(command):
        return all(_quoted_for_the_shell(ctx, part, function) for part in _interpolated(command))
    return _quoted_for_the_shell(ctx, command, function) and not isinstance(command, ast.Constant)


def _deserialization(ctx, node, name, keywords) -> None:
    if name in CODE_LOADERS:
        ctx.add("unsafe-deserialize", node, f"{name}() can execute code in its input.")
    elif name == "yaml.load":
        loader = keywords.get("Loader") or (node.args[1] if len(node.args) > 1 else None)
        if loader is None or "Safe" not in _dotted(loader):
            ctx.add("unsafe-deserialize", node, "yaml.load() without SafeLoader can build arbitrary objects.")
    elif name == "torch.load" and not (keywords.get("weights_only") and getattr(keywords["weights_only"], "value", False)):
        ctx.add("unsafe-deserialize", node, "torch.load() without weights_only=True can execute code.", confidence="medium")


def _targets_secret(statement, function) -> bool:
    targets = []
    if isinstance(statement, ast.Assign):
        targets = [ast.dump(t) for t in statement.targets]
    elif isinstance(statement, ast.Return) and function is not None:
        targets = [function.name]
    return any(SECRET_NAME.search(t) for t in targets)


def _practice_call(ctx, node, name, last, head, keywords, statement) -> None:
    if name == "bool" and node.args and isinstance(node.args[0], ast.Call) and re.search(r"getenv$|environ\.get$", _call_name(node.args[0])):
        ctx.add("env-flag-truthy", node, "The string 'false' is truthy.")
    if name == "int" and node.args and isinstance(node.args[0], ast.BinOp) and _is_money(node.args[0]) and any(isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(node.args[0])):
        ctx.add("float-money", node, "Float arithmetic on money, then truncated by int().")
    if name in ("date.today", "datetime.date.today"):
        ctx.add("naive-datetime", node, "date.today() uses the host's timezone.")
    if name in ("datetime.now", "datetime.datetime.now") and not node.args and "tz" not in keywords:
        ctx.add("naive-datetime", node, "datetime.now() without a timezone.")
    if name == "open" and isinstance(statement, ast.Assign):
        ctx.add("resource-no-context", node)
    if name == "float" and node.args and _is_money(node.args[0]):
        ctx.add("float-money", node, "float() on a money value.")
    if name == "round" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 2 and _is_money(node.args[0]):
        ctx.add("float-money", node, "round(x, 2) on a money value uses binary floats and banker's rounding.")


def _names_of(node: ast.AST) -> list[str]:
    return [child.id if isinstance(child, ast.Name) else child.attr for child in ast.walk(node) if isinstance(child, (ast.Name, ast.Attribute))]


def _value_names(node: ast.AST) -> list[str]:
    """Where a value comes from: `order.amount` is an amount, `payment.retry_count` isn't one because of its receiver, and `correct / total` is a ratio."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Call):
        return _value_names(node.func)
    if isinstance(node, ast.Subscript):
        return _value_names(node.value)
    if isinstance(node, ast.UnaryOp):
        return _value_names(node.operand)
    if isinstance(node, ast.BoolOp):
        return [name for value in node.values for name in _value_names(value)]
    if isinstance(node, ast.BinOp):
        return _value_names(node.left) + ([] if isinstance(node.op, ast.Div) else _value_names(node.right))
    return []


def _is_money(node: ast.AST) -> bool:
    return any(MONEY_NAME.search(name) for name in _value_names(node))


def _is_remote_call(name: str, last: str, head: str) -> bool:
    receiver = name.rsplit(".", 1)[0].lower() if "." in name else ""
    if (head in HTTP_MODULES and last in HTTP_VERBS) or last == "urlopen" or (last in QUERY_METHODS and receiver):
        return True
    if DATA_RECEIVER.search(receiver) and DATA_READ.match(last):
        return True
    if re.search(r"\.objects\.(?:get|filter)$|\.query\.(?:get|filter|filter_by)$", name):
        return True
    return last in ("get", "post", "put", "delete") and bool(re.search(r"session|client|http", receiver))


def _in_loop(ctx, node, name, last, head, function) -> None:
    if not (ctx.is_test or ctx.is_script or MIGRATION_PATH.search(ctx.path)) and _is_remote_call(name, last, head):  # these run once, or against no real load
        ctx.add("query-in-loop", node, f"{name}() runs once per item.")
    if name == "sorted" or (last == "sort" and isinstance(node.func, ast.Attribute)):
        _resort(ctx, node, last, function)
    if name == "re.compile":
        ctx.add("regex-compile-loop", node)
    if name in ARRAY_GROWERS:
        ctx.add("dataframe-grow-loop", node, f"{name}() copies everything on each iteration.")
    if name in ("open", "os.fsync"):
        ctx.add("io-in-loop", node, f"{name}() per item.")
    _hardware_in_loop(ctx, node, name, last)
    if name in TASK_STARTERS and (function is None or not BOUNDING_WORDS.search(ast.dump(function))):
        ctx.add("unbounded-concurrency", node, f"{name}() per item with no limit.")
    is_linear_method = last in ("remove", "index", "count") and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
    if is_linear_method and function is not None and _is_local_list(node.func.value.id, function):
        ctx.add("list-membership-in-loop", node, f"list.{last}() is linear, so this loop is quadratic.")


def _resort(ctx, node: ast.Call, last: str, function: ast.AST | None) -> None:
    """A sort repeated on every pass over the same data: a list the loop keeps adding to, or one that never changes. Sorting what this pass
    produced, as `sorted(row.tags)` or `sorted(d[k])`, is fine."""
    sorting = node.args[0] if node.args else node.func.value if last == "sort" else None  # `np.sort(m)` sorts m, `xs.sort()` sorts xs
    where = (node.lineno, node.col_offset)
    passes = [(fresh, carried) for start, end, fresh, carried in _loop_bodies(function or ctx.tree) if start <= where <= end]
    if sorting is None or not passes:
        return
    # What it reads: not a comprehension's own names, a called function, or a module, since `os.listdir(p)` changes with p, not os.
    skip = {name.id for name in ast.walk(sorting) if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store)} | set(ctx.imported_names) | _BUILTINS
    parents = {id(child): parent for parent in ast.walk(sorting) for child in ast.iter_child_nodes(parent)}
    fresh, carried = passes[-1]
    reads = [(name.id, _read_as(name, parents, fresh)) for name in ast.walk(sorting) if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load)
             and name.id not in skip and not (isinstance(parents.get(id(name)), ast.Call) and parents[id(name)].func is name)]
    names = {name for name, _ in reads}
    repeated = {name for name, how in reads if how == "prefix" or (how == "whole" and name in carried)} | (names if not names & fresh else set())
    if repeated:
        ctx.add("sort-in-loop", node, f"{last}() sorts {', '.join(sorted(repeated))} again on every pass. Sort once outside the loop, or keep it ordered "
                "with bisect.insort or heapq.")


def _read_as(name: ast.Name, parents: dict, fresh: frozenset) -> str:
    """How a sort reads a name: a method called on it ("receiver"), one element chosen by this pass ("item"), a prefix or suffix that moves with
    the pass, as a running median's `xs[:i + 1]` ("prefix"), or all of it ("whole")."""
    parent = parents.get(id(name))
    if isinstance(parent, ast.Attribute) and isinstance(parents.get(id(parent)), ast.Call) and parents[id(parent)].func is parent:
        return "receiver"
    if not (isinstance(parent, ast.Subscript) and parent.value is name):
        return "whole"
    index = parent.slice
    if isinstance(index, ast.Slice):
        lower, upper = (end is not None and bool(_names_in(end) & fresh) for end in (index.lower, index.upper))
        return "prefix" if lower != upper else "item" if lower else "whole"
    return "item" if _names_in(index) & fresh else "whole"


_GROWS = {"append", "extend", "insert", "add", "appendleft", "update", "setdefault"}


@functools.lru_cache(maxsize=16)
def _loop_bodies(scope: ast.AST) -> tuple:
    """Each loop in a scope as (body start, body end, fresh, carried), innermost last. Fresh names are made anew on each pass: its targets, and
    names bound by `with ... as`, `:=` or an assignment from something other than themselves. Carried names outlive a pass and grow in it, as
    `items = sorted(items + [r])`, `seen[k] = r` or `seen.append(r)`."""
    bodies = []
    for loop in (node for node in _walk_own(scope) if isinstance(node, (ast.For, ast.AsyncFor, ast.While))):
        fresh = set() if isinstance(loop, ast.While) else _bound(loop.target)
        carried = set()
        for node in (node for part in loop.body for node in ast.walk(part)):
            made, kept = _pass_names(node)
            fresh |= made
            carried |= kept
        bodies.append(((loop.body[0].lineno, loop.body[0].col_offset), (loop.body[-1].end_lineno, loop.body[-1].end_col_offset),
                       frozenset(fresh), frozenset(carried - fresh)))
    return tuple(sorted(bodies, key=lambda body: body[0]))


def _pass_names(node: ast.AST) -> tuple[set[str], set[str]]:
    """What one node of a loop body makes anew on each pass, and what it carries over and grows."""
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        used, bound = _names_in(node.value), set().union(*(_bound(target) for target in targets))
        indexed = {target.value.id for target in targets if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)}
        return bound - used, (bound & used) | indexed
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        return set(), {node.target.id}
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return set().union(*(_bound(item.optional_vars) for item in node.items if item.optional_vars is not None)), set()
    if isinstance(node, ast.NamedExpr):
        return _bound(node.target), set()
    if isinstance(node, ast.ExceptHandler) and node.name:
        return {node.name}, set()
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _GROWS and isinstance(node.func.value, ast.Name):
        return set(), {node.func.value.id}
    return set(), set()


def _bound(target: ast.AST) -> set[str]:
    """Names a target binds, through tuples and `*rest`. `seen[k] = r` binds none."""
    return {name.id for name in ast.walk(target) if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store)}


def _hardware_in_loop(ctx, node, name, last) -> None:
    if ctx.imports_numeric and (last in ("item", "cuda") or (last in ("cpu", "numpy") and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call))):
        ctx.add("transfer-in-loop", node, f".{last}() inside a loop.")
    if name == "ray.get" and node.args:
        if ".remote" in ast.dump(node.args[0]) or "remote" in ast.dump(node.args[0]):
            ctx.add("remote-get-in-loop", node, "ray.get() per item waits for each result before starting the next.", confidence="high")
        else:
            ctx.add("remote-get-in-loop", node, "ray.get() inside a loop.")


def _is_local_list(name: str, function: ast.AST) -> bool:
    for other in _walk_own(function):
        if isinstance(other, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in other.targets):
            if isinstance(other.value, ast.List) or (isinstance(other.value, ast.Call) and _call_name(other.value) == "list"):
                return True
    return False


def _gather(ctx, node, name, last, function) -> None:
    if name == "asyncio.gather" and any(isinstance(arg, ast.Starred) and isinstance(arg.value, (ast.ListComp, ast.GeneratorExp, ast.Name)) for arg in node.args):
        if function is None or not re.search(r"semaphore|boundedsemaphore", ast.dump(function), re.I):
            ctx.add("unbounded-concurrency", node, "gather() starts every task at once.", confidence="low" if isinstance(node.args[0].value, ast.Name) else "medium")
    if name in ("multiprocessing.Pool", "Pool", "ProcessPoolExecutor", "concurrent.futures.ProcessPoolExecutor") and ctx.imports_numeric:
        ctx.add("oversubscription", node)


def _materialize(ctx, node, name, last, keywords) -> None:
    if last in ("readlines", "fetchall"):
        ctx.add("materialize-all", node, f"{last}() loads everything into memory.")


def _reinvented(ctx, node, name, last, keywords, statement) -> None:
    if name == "open" and node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).endswith(".env"):
        ctx.add("handrolled-dotenv", node)
    if last in ("findall", "search", "match", "sub", "finditer") and head_is_re(name) and node.args and isinstance(node.args[0], ast.Constant) \
            and re.search(r"<(?:a|div|span|td|tr|table|p|img|li|h\d)\b|href=", str(node.args[0].value)):
        ctx.add("handrolled-html-parse", node)
