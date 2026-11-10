"""Python rules for what agents are measured or reported to get wrong, each reading the whole tree on its own so the main walk doesn't grow. docs/large-codebase-failures.md says which failure each answers."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

from .py_helpers import looks_like_auth_check
from .rules_py_flow import _LINTER_DIRECTIVE

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_DECORATED_TWICE_ON_PURPOSE = re.compile(r"overload|setter|getter|deleter|register|dispatch")
_REQUEST_READ = re.compile(r"^(?:await )?(?:flask\.)?request\.(?:args|GET|POST|form|values|json|data|query_params|params|headers|cookies|get_json|query_string|body|files)\b")
_SENSITIVE_NAME = re.compile(r"^(?:\w*_)?(?:password|passwd|pwd|secret|api_?key|apikey|private_?key|access_?key|ssn|credit_?card|card_?number|cvv|access_token|auth_token|refresh_token|id_token|api_token|bearer_token|session_token|client_secret)$", re.I)
_LOGGER = re.compile(r"(?:^|[._])(?:log|logger|logging)$", re.I)
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
_FAKE_VALUE = re.compile(r"(?:^|[._])(?:mock|fake|dummy|stub|sample|placeholder|hardcoded)(?:[._(]|\w*$)", re.I)
_SUCCESS_KEY = {"success", "succeeded", "ok"}
_TASK_STARTERS = {"asyncio.create_task", "asyncio.ensure_future", "loop.create_task", "self.loop.create_task", "asyncio.get_event_loop().create_task", "asyncio.get_running_loop().create_task"}
_TAKES_A_LOCK = re.compile(r"select_for_update|with_for_update|(?-i:\bF\()|atomic|transaction|\bbegin\(|\block\b|Lock\(|FOR UPDATE", re.I)
_COMMITS = {"session", "db", "conn", "connection"}
_IS_A_TRANSACTION = re.compile(r"atomic|transaction|\bbegin\(|autocommit|rollback|\.commit\(\)", re.I)
_SQL_WRITE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE)\b", re.I)
_CLOCKS = {"time.time", "time.perf_counter", "time.monotonic", "time.process_time", "datetime.now", "datetime.datetime.now", "datetime.utcnow"}
_VARIES = {"time.time", "time.monotonic", "datetime.now", "datetime.datetime.now", "datetime.utcnow", "datetime.today", "date.today", "datetime.date.today", "random.random", "random.randint", "random.choice", "uuid.uuid4", "uuid4"}
_NAMES_A_TEST_FILE = re.compile(r"(?:^|/)tests?/[^\"']*\.py$|(?:^|/)test_\w+\.py$")
_TAR_RECEIVER = re.compile(r"(?:^|[._])(?:tar|tarball|tarfile|tf)\d*\.extractall$", re.I)
_RESPONSE_RECEIVER = re.compile(r"(?:^|[._])(?:resp|response|res)\.set_cookie$")
_DEPENDS_ON_THE_PLATFORM = re.compile(r"\b(?:sys|os|platform|support|hasattr|version|shutil|importlib)\b")
_SPLITS = {"train_test_split", "cross_val_score", "KFold", "StratifiedKFold"}


def _text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (ValueError, RecursionError, AttributeError):
        return ""


def _dump(nodes: list) -> str:
    return "\n".join(ast.dump(node) for node in nodes)


def _is_test_function(node: ast.AST) -> bool:
    return isinstance(node, FUNCTIONS) and node.name.startswith("test")


def _redefined(tree: ast.Module, is_test: bool) -> Iterator[tuple]:
    """A second plain def of one name in one scope, with nothing using the first between them. Agents add a new version below the old one, and the old one quietly stops mattering."""
    def scope(body: list) -> Iterator[tuple]:
        seen: dict[str, int] = {}
        for statement in body:
            if isinstance(statement, FUNCTIONS):
                decorators = [_text(decorator) for decorator in statement.decorator_list]
                if not decorators and statement.name in seen:
                    first_runs_never = is_test and statement.name.startswith("test")
                    yield ("redefined-def", statement.lineno, f"{statement.name} is defined again here, replacing the one at line {seen[statement.name]}" + (", so that test never runs." if first_runs_never else "."), {"severity": "high"} if first_runs_never else {})
                if any(_DECORATED_TWICE_ON_PURPOSE.search(text) for text in decorators):
                    seen.pop(statement.name, None)
                else:
                    seen[statement.name] = statement.lineno
            elif isinstance(statement, ast.ClassDef):
                yield from scope(statement.body)
            else:
                for name in {node.id for node in ast.walk(statement) if isinstance(node, ast.Name)} & set(seen):
                    del seen[name]
    yield from scope(tree.body)


def _rebound_names(tree: ast.Module, top_level: dict) -> set[str]:
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)}
    names |= {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    names |= {(alias.asname or alias.name).split(".")[0] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    defined = [node for node in ast.walk(tree) if isinstance(node, FUNCTIONS + (ast.ClassDef,))]
    names |= {node.name for node in defined if node.name not in top_level or top_level[node.name] is not node}
    return names


def _arity_problem(function: ast.AST, call: ast.Call) -> str | None:
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    names = [item.arg for item in positional]
    required = names[:len(names) - len(arguments.defaults)]
    given = len(call.args)
    if given > len(names) and arguments.vararg is None:
        return f"takes at most {len(names)} positional arguments and gets {given}"
    keywords = {keyword.arg for keyword in call.keywords}
    keyword_only = {item.arg for item in arguments.kwonlyargs}
    unknown = sorted(keywords - set(names) - keyword_only) if arguments.kwarg is None else []
    if unknown:
        return f"has no parameter {unknown[0]}"
    missing = [name for name in required[given:] if name not in keywords]
    missing += sorted(item.arg for item, default in zip(arguments.kwonlyargs, arguments.kw_defaults) if default is None and item.arg not in keywords)
    return f"needs {missing[0]}, which isn't passed" if missing else None


def _wrong_arg_count(tree: ast.Module) -> Iterator[tuple]:
    """Only a plain function defined once at the top of this module and never rebound, since then this call can't mean anything else."""
    top_level = {node.name: node for node in tree.body if isinstance(node, FUNCTIONS) and not node.decorator_list}
    defined_once = [node.name for node in tree.body if isinstance(node, FUNCTIONS + (ast.ClassDef,))]
    candidates = {name: node for name, node in top_level.items() if defined_once.count(name) == 1}
    rebound = _rebound_names(tree, candidates)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)) or node.func.id not in candidates or node.func.id in rebound:
            continue
        if any(isinstance(argument, ast.Starred) for argument in node.args) or any(keyword.arg is None for keyword in node.keywords):
            continue
        problem = _arity_problem(candidates[node.func.id], node)
        if problem:
            yield "wrong-arg-count", node.lineno, f"{node.func.id} {problem}.", {}


def _same_but_for_underscores(one: str, other: str) -> bool:
    return one != other and one.replace("_", "") == other.replace("_", "")


def _names_a_class_defines(node: ast.ClassDef) -> set[str]:
    defined = {item.name for item in ast.walk(node) if isinstance(item, FUNCTIONS + (ast.ClassDef,))}
    defined |= {target.id for item in node.body if isinstance(item, ast.Assign) for target in item.targets if isinstance(target, ast.Name)}
    return defined | {item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}


def _could_get_attributes_elsewhere(node: ast.ClassDef, defined: set[str]) -> bool:
    has_parents = any(_text(base) != "object" for base in node.bases) or bool(node.keywords)
    return bool(node.decorator_list) or has_parents or bool({"__getattr__", "__getattribute__"} & defined) or any(isinstance(item, ast.Call) and getattr(item.func, "id", "") == "setattr" for item in ast.walk(node))


def _self_attributes(tree: ast.Module) -> Iterator[tuple]:
    """A read of self.x that nothing sets, when a name differing only by underscores is set: `self._session_id` set and `self.session_id` read."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        defined = _names_a_class_defines(node)
        if _could_get_attributes_elsewhere(node, defined):
            continue
        attributes = [item for item in ast.walk(node) if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name) and item.value.id == "self"]
        assigned = {item.attr for item in attributes if not isinstance(item.ctx, ast.Load)}
        unknown = {}
        for item in attributes:
            if isinstance(item.ctx, ast.Load) and item.attr not in assigned | defined and not item.attr.startswith("__"):
                unknown.setdefault(item.attr, item.lineno)
        for attribute, line in unknown.items():
            close = sorted(name for name in assigned if _same_but_for_underscores(attribute, name))
            if close:
                yield "undefined-self-attribute", line, f"self.{attribute} is read here and nothing in {node.name} sets it. It does set {close[0]}.", {}


def _identical_branches(tree: ast.Module) -> Iterator[tuple]:
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and node.orelse and _dump(node.body) == _dump(node.orelse) and not all(isinstance(item, ast.Pass) for item in node.body):
            yield "identical-branches", node.lineno, "Both branches of this if do the same thing, so the condition decides nothing.", {}


def _reports_success(value: ast.AST) -> bool:
    if not isinstance(value, ast.Dict):
        return False
    for key, item in zip(value.keys, value.values):
        name = key.value if isinstance(key, ast.Constant) else None
        said = item.value if isinstance(item, ast.Constant) else None
        if (name in _SUCCESS_KEY and said is True) or (name == "status" and str(said).lower() in ("ok", "success", "succeeded")):
            return True
    return False


def _hidden_failures(tree: ast.Module, comment_lines: set | frozenset = frozenset(), text: str = "") -> Iterator[tuple]:
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler):
            continue
        for statement in handler.body:
            if not isinstance(statement, ast.Return) or statement.value is None:
                continue
            if _reports_success(statement.value):
                yield "failure-reported-as-success", statement.lineno, "This handler catches a failure and returns success, so the caller can't tell.", {}
            elif not isinstance(statement.value, (ast.Constant, ast.Dict, ast.List)) and _FAKE_VALUE.search(_text(statement.value)):
                yield "fallback-fake", statement.lineno, f"When the real call fails this returns `{_text(statement.value)[:50]}`, so a failure looks like data.", {}
    yield from _same_answer_on_failure(tree, comment_lines, text)


def _success_constant(value: ast.AST | None) -> object:
    if isinstance(value, ast.Constant) and (value.value is True or (isinstance(value.value, str) and value.value.lower() in ("ok", "success", "succeeded"))):
        return value.value
    return None


def _own_nodes(function: ast.AST) -> Iterator[ast.AST]:
    """A function's nodes, not those of functions or classes defined inside it."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _same_answer_on_failure(tree: ast.Module, comment_lines: set | frozenset = frozenset(), text: str = "") -> Iterator[tuple]:
    """`return True` after the work and again in `except Exception`. A narrow handler returning success is often deliberate, as when a missing
    file means already deleted, so only a broad one counts. An authorization check doing this is `fail-open`'s."""
    for function in ast.walk(tree):
        if not isinstance(function, FUNCTIONS) or looks_like_auth_check(function):
            continue
        handlers = [node for node in _own_nodes(function) if isinstance(node, ast.ExceptHandler)
                    and (node.type is None or (isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")))]
        if not handlers:
            continue
        inside = {id(node) for handler in handlers for node in ast.walk(handler)}
        succeeded = {_success_constant(node.value) for node in _own_nodes(function) if isinstance(node, ast.Return) and id(node) not in inside} - {None}
        for handler in handlers:
            if any(isinstance(node, ast.Raise) for node in ast.walk(handler)):
                continue
            for statement in handler.body:
                if isinstance(statement, ast.Return) and _success_constant(statement.value) in succeeded:
                    reasoned = _states_a_reason(handler, comment_lines, text)  # "reachable, just restricted": a decision, though still one to question
                    yield ("failure-reported-as-success", statement.lineno,
                           f"{function.name} returns {_text(statement.value)} when it works and the same when it fails, so the caller can't tell.", {"confidence": "low"} if reasoned else {})


def _states_a_reason(node: ast.AST, comment_lines, text: str) -> bool:
    """A comment of a few words inside the node, beyond a bare instruction to a linter."""
    lines = [line for line in range(node.lineno, (node.end_lineno or node.lineno) + 1) if line in comment_lines]
    source = text.split("\n") if lines else []
    return any(len(re.findall(r"[A-Za-z']{2,}", _LINTER_DIRECTIVE.sub("", source[line - 1].split("#", 1)[-1]))) >= 3 for line in lines if line <= len(source))


def _is_outcome_rewrite(node: ast.AST) -> bool:
    return (isinstance(node, ast.Assign) and any(isinstance(target, ast.Attribute) and target.attr == "outcome" for target in node.targets)
            and isinstance(node.value, ast.Constant) and node.value.value == "passed")


def _test_tampering(tree: ast.Module, path: str, is_test: bool, is_script: bool) -> Iterator[tuple]:
    """Ways to make a check report success without the code doing the work, from published cases of reward hacking. Each needs no judgment about what the code is for."""
    for node in ast.walk(tree):
        if _is_outcome_rewrite(node):
            yield "test-harness-tampered", node.lineno, "This rewrites a test's outcome to passed.", {}
        elif isinstance(node, ast.FunctionDef) and node.name == "__eq__" and not is_test and _always_returns_true(node):
            yield "test-harness-tampered", node.lineno, "__eq__ always returns True, so every comparison with this object passes.", {}
        elif isinstance(node, ast.ExceptHandler) and not is_test:
            yield from _skips_a_failure(node)
        elif isinstance(node, ast.Call) and not is_test and not is_script and _text(node.func) in ("open", "Path", "pathlib.Path") and node.args and isinstance(node.args[0], ast.Constant) and _NAMES_A_TEST_FILE.search(str(node.args[0].value)):
            yield "test-harness-tampered", node.lineno, f"This code reads the test file {str(node.args[0].value)[:60]}, and could be taking expected values from it.", {}
        elif isinstance(node, ast.Assign) and not is_test:
            for target in node.targets:
                if isinstance(target, ast.Attribute) and _text(target) in _CLOCKS:
                    yield "test-harness-tampered", node.lineno, f"This replaces {_text(target)}, so anything timed by it measures something else.", {}
    if is_test:
        yield from _clean_exits(tree, path)


def _always_returns_true(function: ast.FunctionDef) -> bool:
    body = [statement for statement in function.body if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))]
    return len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Constant) and body[0].value.value is True


def _skips_a_failure(handler: ast.ExceptHandler) -> Iterator[tuple]:
    """Skipping because an optional import is missing is what a skip is for."""
    if handler.type is not None and re.search(r"ImportError|ModuleNotFoundError", _text(handler.type)):
        return
    for node in (item for statement in handler.body for item in ast.walk(statement)):
        if isinstance(node, ast.Call) and _text(node.func) in ("unittest.SkipTest", "SkipTest", "pytest.skip"):
            yield "test-harness-tampered", node.lineno, f"{_text(node.func)} here turns a caught failure into a skip.", {}


def _exits_cleanly(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _text(node.func) in ("sys.exit", "exit", "quit") and (not node.args or (isinstance(node.args[0], ast.Constant) and node.args[0].value in (0, None)))


def _clean_exits(tree: ast.Module, path: str) -> Iterator[tuple]:
    """Only where a test run executes it: inside a test or in conftest.py, and not under a `with` that expects the exit. A helper script under tests/ may exit however it likes, and os._exit is how a forked child ends."""
    scopes = [node for node in ast.walk(tree) if _is_test_function(node)]
    if path.rsplit("/", 1)[-1] == "conftest.py":
        scopes.append(tree)
    for scope in scopes:
        expected = {id(node) for block in ast.walk(scope) if isinstance(block, ast.With) for statement in block.body for node in ast.walk(statement)}
        for node in ast.walk(scope):
            if _exits_cleanly(node) and id(node) not in expected:
                yield "test-harness-tampered", node.lineno, f"{_text(node.func)} ends the run with a clean exit, so what comes after never runs and the result still reads as passing.", {}


def _is_a_check(node: ast.AST) -> bool:
    if isinstance(node, ast.Assert):
        return True
    name = node.func.attr if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) else ""
    return name.startswith("assert") or name in ("raises", "fail", "warns")


def _under_an_if_alone(function: ast.AST) -> bool:
    """Every check in this test is in the body of an if with no check in its else, so it can pass having checked nothing."""
    checks = [node for node in ast.walk(function) if _is_a_check(node)]
    conditional = set()
    for branch in (node for node in ast.walk(function) if isinstance(node, ast.If)):
        if any(_is_a_check(node) for statement in branch.orelse for node in ast.walk(statement)) or _DEPENDS_ON_THE_PLATFORM.search(_text(branch.test)):
            return False
        conditional |= {id(node) for statement in branch.body for node in ast.walk(statement) if _is_a_check(node)}
    return bool(checks) and len(conditional) == len(checks)


def _test_quality(tree: ast.Module) -> Iterator[tuple]:
    for function in ast.walk(tree):
        if not _is_test_function(function):
            continue
        if _under_an_if_alone(function):
            yield "test-conditional-assert", function.lineno, f"Every check in {function.name} sits under an if, so it can pass having checked nothing.", {}
        for item in (node for node in ast.walk(function) if isinstance(node, ast.Assert)):
            varying = sorted({_text(call.func) for call in ast.walk(item.test) if isinstance(call, ast.Call)} & _VARIES)
            if varying:
                yield "test-nondeterministic", item.lineno, f"This assertion depends on {varying[0]}, which differs between runs.", {}
                break


def _is_log_call(node: ast.Call) -> bool:
    function = node.func
    return isinstance(function, ast.Attribute) and function.attr in _LOG_METHODS and bool(_LOGGER.search(_text(function.value)))


def _logged_values(node: ast.Call) -> Iterator[ast.AST]:
    for argument in node.args:
        if isinstance(argument, ast.JoinedStr):
            yield from (value.value for value in argument.values if isinstance(value, ast.FormattedValue))
        elif not isinstance(argument, ast.Constant):
            yield argument


def _logging(tree: ast.Module, is_script: bool) -> Iterator[tuple]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_print = isinstance(node.func, ast.Name) and node.func.id == "print" and not is_script
        if not (is_print or _is_log_call(node)):
            continue
        for value in _logged_values(node):
            leaf = value.attr if isinstance(value, ast.Attribute) else value.id if isinstance(value, ast.Name) else None
            if leaf and _SENSITIVE_NAME.match(leaf):
                yield "sensitive-log", node.lineno, f"{leaf} goes into the output here, and logs outlive the session.", {}
                break
            if not is_print and _REQUEST_READ.match(_text(value)):
                yield "log-injection", node.lineno, "Text from the request goes straight into a log line, so a newline in it forges an entry.", {}
                break


def _web(tree: ast.Module) -> Iterator[tuple]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
        if name in ("redirect", "HttpResponseRedirect", "RedirectResponse") and node.args and _REQUEST_READ.match(_text(node.args[0])):
            yield "open-redirect", node.lineno, "This redirects to a URL taken from the request, so a link can send users anywhere.", {}
        for keyword in node.keywords:
            if keyword.arg is None and _REQUEST_READ.match(_text(keyword.value)):
                yield "mass-assignment", node.lineno, f"{_text(node.func)[:40]} takes every field the client sends, including any it shouldn't set, such as a role or owner.", {}
        if name == "extractall" and not {keyword.arg for keyword in node.keywords} & {"filter", "members"} and _TAR_RECEIVER.search(_text(node.func)):
            yield "unsafe-extract", node.lineno, "extractall with no filter lets a tar archive write outside the target folder.", {}
        elif name == "set_cookie" and _RESPONSE_RECEIVER.search(_text(node.func)) and "secure" not in {keyword.arg for keyword in node.keywords} and not any(keyword.arg is None for keyword in node.keywords):
            yield "insecure-cookie", node.lineno, "This cookie goes out with no Secure flag.", {}


def _concurrency(tree: ast.Module) -> Iterator[tuple]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _text(node.value.func) in _TASK_STARTERS:
            yield "dropped-task", node.lineno, "Nothing keeps a reference to this task, so it can be collected before it finishes, and its exception goes nowhere.", {}
    for function in ast.walk(tree):
        if not isinstance(function, FUNCTIONS):
            continue
        source = _text(function)
        yield from _lost_update(function, source)
        yield from _writes_apart(function, source)
        yield from _commits_apart(function, source)


def _changes_from_itself(node: ast.AST) -> ast.Attribute | None:
    """`x.n += q`, or `x.n = x.n + q` and `x.n = max(0, x.n - q)`: a new value worked out in Python from the one read. None otherwise."""
    if isinstance(node, ast.AugAssign) and isinstance(node.op, (ast.Add, ast.Sub)):
        target = node.target
    elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.value, (ast.BinOp, ast.Call)):
        target = node.targets[0]
        read = _text(target)
        arithmetic = [inner for inner in ast.walk(node.value) if isinstance(inner, ast.BinOp) and isinstance(inner.op, (ast.Add, ast.Sub))]
        if not any(_text(side) == read for inner in arithmetic for side in (inner.left, inner.right)):
            return None
    else:
        return None
    return target if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id not in ("self", "cls") else None


def _commits_it(save: ast.Call, name: str) -> bool:
    """`order.save()` for the object itself, or a session's commit: `db.commit()`, `self.session.commit()`, `db.session.commit()`."""
    receiver = _text(save.func.value)
    if save.func.attr == "save":
        return receiver == name
    return receiver.rsplit(".", 1)[-1] in _COMMITS


def _lost_update(function: ast.AST, source: str) -> Iterator[tuple]:
    """The object changed has to be the one saved, or a session committing it. `stats.count += 1; img.save()` isn't this."""
    if _TAKES_A_LOCK.search(source):
        return
    saves = [node for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("save", "commit")
             and isinstance(node.func.value, (ast.Name, ast.Attribute))]
    for node in ast.walk(function):
        target = _changes_from_itself(node)
        if target is None:
            continue
        name = target.value.id
        if any(save.lineno > node.lineno and _commits_it(save, name) for save in saves):
            yield "lost-update", node.lineno, f"{_text(target)} is read, changed and saved with no lock or transaction, so two at once lose one update.", {}
            return


def _saves_nothing(call: ast.Call) -> bool:
    """A Django form's `save(commit=False)` builds the instance and writes nothing."""
    return any(keyword.arg == "commit" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False for keyword in call.keywords)


def _writes_apart(function: ast.AST, source: str) -> Iterator[tuple]:
    if _IS_A_TRANSACTION.search(source):
        return
    writes = 0
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "save" and not node.args and not _saves_nothing(node):
                writes += 1
            elif node.func.attr in ("execute", "executemany") and node.args and isinstance(node.args[0], ast.Constant) and _SQL_WRITE.match(str(node.args[0].value)):
                writes += 1
    if writes >= 2:
        yield "multi-write-no-transaction", function.lineno, f"{function.name} writes {writes} times with no transaction, so a failure between them leaves half of it done.", {}


_OPENS_A_TRANSACTION = re.compile(r"atomic|\bbegin(?:_nested)?\(|savepoint|transaction\(", re.I)


def _written_objects(statements: list) -> set[str]:
    """What a run of statements changes: objects whose fields it sets, and what it saves, deletes or adds to a session."""
    written = set()
    for node in (inner for statement in statements for inner in ast.walk(statement)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AugAssign) else []
        written.update(target.value.id for target in targets if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                       and target.value.id not in ("self", "cls"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("save", "delete") and isinstance(node.func.value, ast.Name):
                written.add(node.func.value.id)
            elif node.func.attr in ("add", "add_all", "merge", "delete") and _text(node.func.value).rsplit(".", 1)[-1] in _COMMITS:
                written.update(_text(argument.func if isinstance(argument, ast.Call) else argument) for argument in node.args)
    return written


def _is_commit(statement: ast.AST) -> bool:
    call = statement.value if isinstance(statement, ast.Expr) else None
    call = call.value if isinstance(call, ast.Await) else call
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "commit" and not call.args
            and _text(call.func.value).rsplit(".", 1)[-1] in _COMMITS)


def _commits_apart(function: ast.AST, source: str) -> Iterator[tuple]:
    """One operation committed in two steps: a failure after the first commit keeps the first half, as a debit saved without its credit.
    The commits have to sit in the function's own straight-line body, since a loop committing per batch means to, and the second step has to
    change something the first didn't, since saving one row and then marking it sent is one record's progress."""
    if _OPENS_A_TRANSACTION.search(source):
        return
    body = [statement for statement in function.body]
    commits = [index for index, statement in enumerate(body) if _is_commit(statement)]
    if len(commits) < 2:
        return
    first, second = commits[0], commits[1]
    before, between = _written_objects(body[:first]), _written_objects(body[first + 1:second])
    if before and between - before:
        yield ("multi-write-no-transaction", body[second].lineno, f"{function.name} commits once after changing {', '.join(sorted(before))} and again after "
               f"changing {', '.join(sorted(between - before))}, so a failure between the commits keeps only the first half. Make it one transaction.", {})


def _train_test_leak(tree: ast.Module) -> Iterator[tuple]:
    """Fitting on everything and only then splitting lets the test set shape the model. Order in one scope is all this can see."""
    for scope in [tree, *(node for node in ast.walk(tree) if isinstance(node, FUNCTIONS))]:
        fitted = split = None
        for statement in scope.body:
            if isinstance(statement, FUNCTIONS + (ast.ClassDef,)):
                continue
            for node in ast.walk(statement):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                    fitted = fitted or (node.lineno if name == "fit_transform" else None)
                    split = split or (node.lineno if name in _SPLITS else None)
        if fitted and split and fitted < split:
            yield "train-test-leak", fitted, "This fits on all the data at line %d and splits it at line %d, so the test set leaks into training." % (fitted, split), {}
            return


def findings(tree: ast.Module, path: str, is_test: bool, is_script: bool, comment_lines: set | frozenset = frozenset(), text: str = "") -> list[tuple]:
    """(rule, line, message, overrides) for one parsed module."""
    found = [*_redefined(tree, is_test), *_test_tampering(tree, path, is_test, is_script), *_identical_branches(tree)]
    if is_test:
        return [*found, *_test_quality(tree)]
    return [*found, *_wrong_arg_count(tree), *_self_attributes(tree), *_hidden_failures(tree, comment_lines, text), *_logging(tree, is_script), *_web(tree), *_concurrency(tree), *_train_test_leak(tree)]
