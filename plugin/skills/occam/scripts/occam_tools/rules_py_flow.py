"""Python rules about what runs: control flow, exceptions, comparisons and calls."""

from __future__ import annotations

import ast
import re

from .py_helpers import (
    NESTED_QUANTIFIER,
    AUTH_NAME, COMPARED_SECRET, HTTP_MODULES, HTTP_VERBS, MIGRATION_PATH, MONEY_NAME, _literal_loop_names, QUERY_METHODS, SECRET_NAME, _call_name,
    _dotted, _has_sql, _is_constant_none_or_empty, _is_dynamic_string, _last, _names_in, _only_placeholders,
    _string_parts, _walk_own, head_is_re,
)

SQL_METHODS = {"execute", "executemany", "raw", "text", "query", "executescript", "read_sql", "read_sql_query"}
WEAK_HASHES = {"hashlib.md5", "hashlib.sha1", "md5", "sha1"}
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
        if function is not None and AUTH_NAME.search(function.name):
            for statement in handler.body:
                if isinstance(statement, ast.Return) and isinstance(statement.value, ast.Constant) and statement.value.value is True:
                    ctx.add("fail-open", statement, f"{function.name} returns True when its check errors.")
        if not broad or ctx.is_test:
            continue
        if _drops_error(handler):
            comments = [line for line in range(handler.lineno, (handler.end_lineno or handler.lineno) + 1) if line in ctx.comment_lines]
            confidence = ("low" if _states_a_reason(ctx, comments) else "medium") if comments else None
            ctx.add("swallowed-exception", handler, f"except {caught or ''} drops the error.".replace("  ", " "), **({"confidence": confidence} if confidence else {}))


_NEVER_NONE_NODES = (ast.List, ast.Dict, ast.Set, ast.Tuple, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.JoinedStr, ast.Lambda)
_NEVER_NONE_CALLS = {"str", "int", "float", "bool", "bytes", "list", "dict", "set", "frozenset", "tuple", "len", "sorted", "abs", "range"}


def compares_with_none(node: ast.AST) -> str | None:
    """The name in `name is None`, or None if this isn't that comparison. `==` doesn't count, because a column or a frame can overload it to mean something else."""
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Is, ast.IsNot)):
        return None
    right = node.comparators[0]
    if isinstance(node.left, ast.Name) and isinstance(right, ast.Constant) and right.value is None:
        return node.left.id
    return None


def bound_names(function: ast.AST) -> set[str]:
    """Every name this function's body can rebind, however it does it. Nested functions count, because `nonlocal` reaches out of them."""
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, (ast.Nonlocal, ast.Global)):
            names.update(node.names)
        elif type(node).__name__ in ("MatchAs", "MatchStar") and node.name:
            names.add(node.name)
        elif type(node).__name__ == "MatchMapping" and node.rest:
            names.add(node.rest)
    return names


def _local_names(function: ast.AST | None) -> set[str]:
    if function is None:
        return set()
    return bound_names(function) | {node.arg for node in ast.walk(function) if isinstance(node, ast.arg)}


def _why_never_none(ctx, value: ast.AST, function: ast.AST | None) -> str | None:
    if isinstance(value, _NEVER_NONE_NODES) or (isinstance(value, ast.Constant) and value.value is not None):
        return "a literal"
    awaited = isinstance(value, ast.Await)
    call = value.value if awaited else value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id in _local_names(function) or call.func.id in ctx.shadowed_names:
        return None
    name = call.func.id
    if ctx.never_none_functions.get(name) is awaited:  # only awaiting an `async def` gives what its annotation says
        return f"{name}(), whose return annotation excludes None"
    if name in _NEVER_NONE_CALLS and name not in ctx.function_names and not awaited:
        return f"{name}()"
    return None


def check_none_after_assign(ctx, previous: ast.AST, statement: ast.AST, function: ast.AST | None) -> None:
    """`x = [..]` directly followed by `if x is None:`. Adjacent statements only, so nothing can have changed it in between."""
    if not isinstance(previous, ast.Assign) or len(previous.targets) != 1 or not isinstance(previous.targets[0], ast.Name) or not isinstance(statement, ast.If):
        return
    name = previous.targets[0].id
    if compares_with_none(statement.test) != name:
        return
    why = _why_never_none(ctx, previous.value, function)
    if why:
        ctx.add("impossible-none-check", statement, f"{name} was just assigned from {why}, so it can't be None here.")


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
        if _is_index_loop(node.iter) and ctx.imports_numeric:
            ctx.add("python-loop-over-array", node, "Python index loop in a module that uses numeric arrays.")
    handles_error_with_sleep = False
    for child in node.body:
        if isinstance(child, ast.Try):
            for handler in child.handlers:
                if any(isinstance(n, ast.Call) and _last(_call_name(n)) == "sleep" for s in handler.body for n in ast.walk(s)):
                    handles_error_with_sleep = True
    if handles_error_with_sleep:
        ctx.add("handrolled-retry", node, "A loop that catches and sleeps is a hand-written retry.")


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


def check_assert(ctx, node, function) -> None:
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
    return any(COMPARED_SECRET.search(name) for name in names) or any("hmac" in _text_of(side).lower() for side in sides)


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
        _materialize(ctx, node, name, last, keywords)
        _reinvented(ctx, node, name, last, keywords, statement)


def _security_call(ctx, node, name, last, head, keywords, statement, function) -> None:
    first = node.args[0] if node.args else None
    _command_execution(ctx, node, name, head, keywords, first)
    _regex_literal(ctx, node, name, first)
    _deserialization(ctx, node, name, keywords)
    if last in SQL_METHODS and first is not None and _is_dynamic_string(first) and (last == "execute" or _has_sql(_string_parts(first))) and not _only_placeholders(first, _literal_loop_names(function)):
        # Values are bound as well, so what's interpolated may only be structure, such as a checked column name.
        overrides = {"confidence": "low"} if MIGRATION_PATH.search(ctx.path) else {"confidence": "medium"} if len(node.args) > 1 else {}
        ctx.add("sql-injection", node, f"{name}() receives SQL built from runtime values.", **overrides)
    if name in WEAK_HASHES and not (keywords.get("usedforsecurity") and getattr(keywords["usedforsecurity"], "value", True) is False):
        context = ast.dump(statement) + (function.name if function is not None else "")
        if re.search(r"password|passwd|pwd|secret", context, re.I):
            ctx.add("weak-password-hash", node, f"{name}() on a password or secret.")
        else:
            ctx.add("weak-crypto", node, f"{name}() in use.")
    if head == "random" and last in RANDOM_CALLS and _targets_secret(statement, function):
        ctx.add("insecure-random", node, f"{name}() isn't safe for secrets.")
    if name == "tempfile.mktemp":
        ctx.add("insecure-tempfile", node)
    if name == "os.chmod" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 0o777:
        ctx.add("world-writable", node)


def _regex_literal(ctx, node, name, first) -> None:
    if name.split(".")[0] in ("re", "regex") and isinstance(first, ast.Constant) and isinstance(first.value, str) and NESTED_QUANTIFIER.search(first.value):
        ctx.add("redos-regex", node, "This pattern has a repeated group containing a repeat.")


def _command_execution(ctx, node, name, head, keywords, first) -> None:
    if first is None or isinstance(first, ast.Constant):
        return
    if name in ("eval", "exec"):
        ctx.add("dynamic-eval", node, f"{name}() on a value computed at runtime.")
    shell = keywords.get("shell")
    if head == "subprocess" and isinstance(shell, ast.Constant) and shell.value is True:
        ctx.add("shell-injection", node, f"{name}(shell=True) with a value computed at runtime.")
    elif name in ("os.system", "os.popen"):
        ctx.add("shell-injection", node, f"{name}() with a value computed at runtime.")


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
    if name == "int" and node.args and isinstance(node.args[0], ast.BinOp) and MONEY_NAME.search(_text_of(node.args[0])) and any(isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(node.args[0])):
        ctx.add("float-money", node, "Float arithmetic on money, then truncated by int().")
    if name in ("date.today", "datetime.date.today"):
        ctx.add("naive-datetime", node, "date.today() uses the host's timezone.")
    if name in ("datetime.now", "datetime.datetime.now") and not node.args and "tz" not in keywords:
        ctx.add("naive-datetime", node, "datetime.now() without a timezone.")
    if name == "open" and isinstance(statement, ast.Assign):
        ctx.add("resource-no-context", node)
    if name == "float" and node.args and MONEY_NAME.search(_text_of(node.args[0])):
        ctx.add("float-money", node, "float() on a money value.")
    if name == "round" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 2 and MONEY_NAME.search(_text_of(node.args[0])):
        ctx.add("float-money", node, "round(x, 2) on a money value uses binary floats and banker's rounding.")


def _text_of(node: ast.AST) -> str:
    names = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
    return " ".join(names).replace(" ", "_") if len(names) == 1 else " ".join(names)


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
        ctx.add("sort-in-loop", node, f"{last}() inside a loop.")
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
