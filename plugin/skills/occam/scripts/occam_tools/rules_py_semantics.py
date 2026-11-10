"""Python rules for traps that run without an error and give the wrong answer. Each reads the whole tree on its own.

docs/quality-catalog.md says which failure each answers. Every rule here stays below the severity and confidence that make a
finding serious, so none of them sends an agent back: they show in `scan`, `gate` and audits.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Callable, Iterator

from .py_helpers import ROUTE_DECORATOR_NAME, _walk_own
from .rules_py_agent import FUNCTIONS, _text

LOOPS = (ast.For, ast.AsyncFor)
_FALLBACK_STDLIB = {"abc", "ast", "base64", "calendar", "cmd", "code", "collections", "copy", "csv", "dataclasses", "datetime", "decimal", "email",
                    "enum", "functools", "glob", "hashlib", "html", "http", "inspect", "json", "logging", "math", "numbers", "operator",
                    "pathlib", "platform", "pickle", "profile", "queue", "random", "re", "secrets", "select", "signal", "socket", "sqlite3",
                    "statistics", "string", "struct", "subprocess", "tempfile", "threading", "token", "tokenize", "trace", "typing", "uuid"}
# Python 3.9 has no sys.stdlib_module_names, so it uses the shorter list above. Built-in modules and those the interpreter
# imports before any script runs can't be shadowed by a file, and private ones are left out.
_ALREADY_LOADED = {"os", "io", "abc", "codecs", "site", "stat", "posixpath", "ntpath", "genericpath", "encodings", "test", "this", "antigravity", "idlelib", "turtledemo"}
STDLIB_NAMES = frozenset(name for name in getattr(sys, "stdlib_module_names", _FALLBACK_STDLIB)
                         if not name.startswith("_") and name not in _ALREADY_LOADED and name not in sys.builtin_module_names)
# A script run directly puts its own folder first on the import path. These are the folders scripts are usually run from.
_SCRIPT_FOLDERS = {"", "scripts", "script", "bin", "tools", "examples", "src"}
# Calls that keep a function to call later, so a loop variable it reads has moved on by then. `func=` and `fn=` are left
# out, since `df.apply(func=...)` calls it straight away.
_KEEPS_FOR_LATER = {"append", "appendleft", "insert", "add", "setdefault", "connect", "register", "add_done_callback", "call_soon",
                    "call_soon_threadsafe", "call_later", "call_at", "add_callback", "subscribe", "on", "bind", "after", "submit", "apply_async",
                    "add_job", "add_listener", "add_handler", "addEventListener", "schedule"}
# Where a caught exception is kept to raise or report later.
_KEEPERS = {"append", "appendleft", "insert", "add", "put", "put_nowait", "set_exception"}
_CALLBACK_KEYWORDS = {"command", "callback", "target", "on_click", "on_change", "handler", "done_callback"}
# Changes that skip list items or make a dict or set raise. append and extend are left out: a list grown while it's walked is
# a known worklist idiom.
_RESIZES = {"remove", "pop", "insert", "clear", "discard", "add", "update", "setdefault", "popitem"}
_VIEWS = {"items", "keys", "values"}
_MUTATORS = {"append", "extend", "insert", "add", "update", "setdefault", "pop", "remove", "clear", "discard", "popitem", "appendleft"}
_MUTABLE_CALLS = {"list", "dict", "set", "defaultdict", "collections.defaultdict", "OrderedDict", "collections.OrderedDict", "deque", "collections.deque", "Counter", "collections.Counter"}
_TIMERS = {"time.perf_counter", "time.time", "time.monotonic", "perf_counter", "timeit.default_timer", "default_timer", "time.perf_counter_ns", "time.monotonic_ns"}
_USES_A_GPU = re.compile(r"\btorch\.cuda\b|\.cuda\(\)|device\s*=\s*[\"']cuda|\.to\(\s*[\"']cuda|\bimport cupy\b|\bfrom cupy\b|\bimport jax\b|\bfrom jax\b")
_GPU_WORK = re.compile(r"\b(?:torch|cp|cupy|jnp|jax|F)\.\w+\(|\bmodel\(|\.cuda\(|\.to\(")
_SYNCS = re.compile(r"\bsynchronize\(|\bblock_until_ready\(|\belapsed_time\(|\.cpu\(\)|\.item\(\)|\.numpy\(\)|\.tolist\(\)")
_NAN = {"math.nan", "np.nan", "numpy.nan", "float('nan')", 'float("nan")', "float('NaN')", 'float("NaN")', "np.NaN", "torch.nan"}
# A fresh wrapper from these compiles again. JAX and torch.compile cache by function or code object, so they're left out.
_COMPILERS = {"numba.jit", "numba.njit", "njit", "tf.function", "torch.jit.trace"}
_CTYPES_LIBRARY = re.compile(r"^(?:ctypes\.)?(?:CDLL|PyDLL|WinDLL|OleDLL|cdll\.LoadLibrary|windll\.LoadLibrary|ctypes\.cdll\.LoadLibrary)$")
# The check has to read storage: a query chain ending in a lookup. Bounded, since `.*` here would be quadratic on a long condition.
_EXISTS = re.compile(r"\.(?:objects|query|filter|filter_by|where|select|execute)\b.{0,300}?\.(?:exists|first|one_or_none|count|scalar|fetchone)\(\)|\.find_one\(")
_SESSIONS = re.compile(r"(?:^|\.)(?:session|db_session|db)$")
_RETRY_DECORATOR = re.compile(r"(?:^|\.)(?:retry|retrying|on_exception|on_predicate)$")
# Effects a repeat makes twice: money moving and messages going out. A model call or a read sent by POST repeats harmlessly.
_NOT_REPEATABLE = re.compile(r"\b(?:charge|refund|payout|transfer|pay)\w*\(|\bstripe\.\w+\.create\(|\bsend_(?:email|mail|sms|message|notification|invoice)\w*\(|\bpublish\(", re.I)
_IDEMPOTENT = re.compile(r"idempot|dedup|request_id|requestid|Idempotency-Key", re.I)
_VERIFIES = re.compile(r"hmac|signature|verify|construct_event|compare_digest|validate_request|webhook_secret|signing_secret|x-hub-signature|svix|webhooks\.", re.I)
_TRACEBACK = re.compile(r"\btraceback\.format_exc\(|\btraceback\.format_exception\(")
_RESPONDS = re.compile(r"(?:^|\.)(?:jsonify|JSONResponse|Response|HttpResponse|JsonResponse|make_response|PlainTextResponse|HTMLResponse)$")


def _names(target: ast.AST) -> set[str]:
    return {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}


def _calls(nodes) -> Iterator[ast.Call]:
    return (node for node in nodes if isinstance(node, ast.Call))


def _method(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else ""


def _functions(tree: ast.Module) -> Iterator[ast.AST]:
    return (node for node in ast.walk(tree) if isinstance(node, FUNCTIONS))


def _assigned_from(scope: ast.AST, matches: Callable[[ast.AST], bool]) -> set[str]:
    """Names this scope binds, in a plain `name = value`, to a value that matches."""
    return {node.targets[0].id for node in _walk_own(scope) if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) and matches(node.value)}


def _parameters(function: ast.AST) -> set[str]:
    arguments = function.args
    every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *(a for a in (arguments.vararg, arguments.kwarg) if a)]
    return {argument.arg for argument in every}


def _free_names(function: ast.AST) -> set[str]:
    """Names a function or lambda reads and doesn't bind itself. A default such as `i=i` is a parameter, so it isn't free."""
    bound = _parameters(function)
    read: set[str] = set()
    for statement in [function.body] if isinstance(function, ast.Lambda) else function.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Name):
                (read if isinstance(node.ctx, ast.Load) else bound).add(node.id)
    return read - bound


# ---------------------------------------------------------------- late binding

def _late_binding(tree: ast.Module) -> Iterator[tuple]:
    """A function made in a loop and kept for later reads the loop variable when it's called, by which time the loop has moved on."""
    for node in ast.walk(tree):
        if isinstance(node, LOOPS):
            yield from _kept_functions(node, _names(node.target))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            yield from _lambda_built_per_item(node)


def _lambda_built_per_item(comprehension: ast.AST) -> Iterator[tuple]:
    made = comprehension.value if isinstance(comprehension, ast.DictComp) else comprehension.elt
    targets = set().union(*(_names(generator.target) for generator in comprehension.generators))
    read = _free_names(made) & targets if isinstance(made, ast.Lambda) else set()
    if read:
        variable = min(read)
        yield "loop-variable-closure", made.lineno, f"Every lambda built here reads `{variable}` when called, so all of them see its last value. Bind it as a default, `lambda {variable}={variable}: ...`.", {}


def _kept_functions(loop: ast.AST, targets: set[str]) -> Iterator[tuple]:
    defined = {node.name: node for statement in loop.body for node in ast.walk(statement) if isinstance(node, FUNCTIONS) and _free_names(node) & targets}
    for statement in loop.body:
        for node in ast.walk(statement):
            for kept, how in _kept_here(node):
                function = kept if isinstance(kept, ast.Lambda) else defined.get(kept.id) if isinstance(kept, ast.Name) else None
                read = _free_names(function) & targets if function is not None else set()
                if read:
                    variable = min(read)
                    yield "loop-variable-closure", kept.lineno, f"This function is {how} and reads the loop variable `{variable}` when it's called, after the loop has moved on, so each copy sees the last value. Bind it as a default (`{variable}={variable}`) or use functools.partial.", {}
                    return


def _kept_here(node: ast.AST) -> Iterator[tuple[ast.AST, str]]:
    if isinstance(node, ast.Call):
        if _method(node) in _KEEPS_FOR_LATER:
            yield from ((argument, f"passed to {_method(node)}() for later") for argument in node.args)
        yield from ((keyword.value, f"kept as {keyword.arg}=") for keyword in node.keywords if keyword.arg in _CALLBACK_KEYWORDS)
    elif isinstance(node, ast.Assign) and any(isinstance(target, (ast.Subscript, ast.Attribute)) for target in node.targets):
        yield node.value, "stored"


# ---------------------------------------------------------------- changing a collection while walking it

def _resizes(statement: ast.AST, walked: str) -> bool:
    """Whether this statement changes the size of `walked` now. A lambda or function in it runs later, so it doesn't count."""
    for node in [statement, *_walk_own(statement)]:
        if isinstance(node, ast.Call) and _method(node) in _RESIZES and _text(node.func.value) == walked:
            return True
        if isinstance(node, ast.Delete) and any(isinstance(target, ast.Subscript) and _text(target.value) == walked for target in node.targets):
            return True
    return False


def _simple_statements(block: list, stops_after: bool, in_inner_loop: bool) -> Iterator[tuple[ast.stmt, bool]]:
    """Each simple statement in a loop body, with whether the walked loop stops before its next item. A break inside a nested
    loop only leaves that loop, so it doesn't count. A break or return later in an enclosing block does."""
    stops_later, stops = [], stops_after
    for statement in reversed(block):
        stops_later.append(stops)
        stops = stops or isinstance(statement, (ast.Return, ast.Raise)) or (isinstance(statement, ast.Break) and not in_inner_loop)
    for statement, stops in zip(block, reversed(stops_later)):
        if isinstance(statement, (*FUNCTIONS, ast.ClassDef)):
            continue
        children = _child_blocks(statement)
        if not children:
            yield statement, stops
        inner = in_inner_loop or isinstance(statement, (*LOOPS, ast.While))
        for child in children:
            yield from _simple_statements(child, stops, inner)


def _child_blocks(statement: ast.stmt) -> list[list]:
    blocks = [getattr(statement, field, None) for field in ("body", "orelse", "finalbody")]
    blocks = [block for block in blocks if isinstance(block, list) and block and isinstance(block[0], ast.stmt)]
    return blocks + [handler.body for handler in getattr(statement, "handlers", [])]


def _walked_name(loop: ast.AST) -> str | None:
    walked = loop.iter
    if isinstance(walked, ast.Call) and _method(walked) in _VIEWS and not walked.args:
        walked = walked.func.value
    name = _text(walked) if isinstance(walked, (ast.Name, ast.Attribute)) else None
    return None if name in ("self", "cls") else name  # a container walking itself has its own rules for what its methods change


def _mutated_while_walked(tree: ast.Module) -> Iterator[tuple]:
    """Removing from a list while looping over it skips the next item, and resizing a dict or set raises. A loop that stops right after is fine."""
    for loop in ast.walk(tree):
        name = _walked_name(loop) if isinstance(loop, LOOPS) else None
        if name is None:
            continue
        hit = next((statement for statement, stops in _simple_statements(loop.body, False, False)
                    if not stops and not isinstance(statement, (ast.Break, ast.Return, ast.Raise)) and _resizes(statement, name)), None)
        if hit is not None:
            yield "mutated-while-iterating", hit.lineno, f"This changes the size of `{name}` while the loop walks it, so a list skips items and a dict or set raises RuntimeError. Loop over a copy, such as list({name}), or build a new one.", {}


# ---------------------------------------------------------------- state shared by every instance

def _is_mutable(value: ast.AST) -> bool:
    if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    return isinstance(value, ast.Call) and _text(value.func) in _MUTABLE_CALLS


def _kind(value: ast.AST) -> str:
    if isinstance(value, (ast.Set, ast.SetComp)) or _text(getattr(value, "func", value)) == "set":
        return "set"
    if isinstance(value, (ast.Dict, ast.DictComp)) or _text(getattr(value, "func", value)).endswith(("dict", "OrderedDict", "Counter")):
        return "dict"
    return "list"


def _class_level_mutables(node: ast.ClassDef) -> dict[str, ast.Assign]:
    return {statement.targets[0].id: statement for statement in node.body if isinstance(statement, ast.Assign) and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name) and _is_mutable(statement.value)}


def _instance_methods(node: ast.ClassDef) -> list:
    return [item for item in node.body if isinstance(item, FUNCTIONS) and not {_text(d) for d in item.decorator_list} & {"classmethod", "staticmethod"}]


def _set_on_self(methods: list) -> set[str]:
    """Attributes some method assigns on self, which gives each instance its own and hides the class-level one."""
    found = set()
    for method in methods:
        for statement in ast.walk(method):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, (ast.AnnAssign, ast.AugAssign)) else []
            found.update(target.attr for target in targets if isinstance(target, ast.Attribute) and _text(target.value) == "self")
    return found


def _changed_through_self(method: ast.AST, names: set[str]) -> str | None:
    for node in ast.walk(method):
        if isinstance(node, ast.Call) and _method(node) in _MUTATORS:
            owner = node.func.value
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            owner = next((target.value for target in targets if isinstance(target, ast.Subscript)), None)
        else:
            continue
        if isinstance(owner, ast.Attribute) and _text(owner.value) == "self" and owner.attr in names:
            return owner.attr
    return None


def _class_shared_mutables(tree: ast.Module) -> Iterator[tuple]:
    """A list or dict set in the class body is one object shared by every instance. Changed through self, it looks per-instance and isn't."""
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        shared = _class_level_mutables(node)
        methods = _instance_methods(node) if shared else []
        candidates = set(shared) - _set_on_self(methods)
        found = next(((method, name) for method in methods for name in [_changed_through_self(method, candidates)] if name), None)
        if found:
            method, name = found
            yield "shared-class-mutable", shared[name].lineno, f"`{name}` is one {_kind(shared[name].value)} shared by every {node.name}, and {method.name}() changes it through self, so each instance sees the others' changes. If each needs its own, create it in __init__.", {}


# ---------------------------------------------------------------- cancellation

def _catches_cancellation(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return False  # bare-except already says this
    caught = {_text(node).rsplit(".", 1)[-1] for node in (handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type])}
    return bool(caught & {"CancelledError", "BaseException"})


def _swallows(handler: ast.ExceptHandler) -> bool:
    """No raise, no uncancel(), and the exception isn't stored to raise later, as in `err = e`, `errors.append(e)` or `future.set_exception(e)`.
    Logging it, or keeping only its text, isn't keeping it."""
    handled = [node for statement in handler.body for node in ast.walk(statement)]
    values = [node.value for node in handled if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None]
    values += [argument for call in _calls(handled) if _method(call) in _KEEPERS for argument in call.args]
    kept = {item.id for value in values for item in (value.elts if isinstance(value, (ast.Tuple, ast.List)) else [value]) if isinstance(item, ast.Name)}
    stored = handler.name is not None and handler.name in kept
    return not stored and not any(isinstance(node, ast.Raise) for node in handled) and not any(_method(node) == "uncancel" for node in _calls(handled))


def _cancelled_by(function: ast.AST) -> set[str]:
    """What a coroutine cancels: `t.cancel()`, and for `for t in tasks: t.cancel()`, the collection `tasks` too."""
    cancelled = {_text(node.func.value) for node in _calls(_walk_own(function)) if _method(node) == "cancel"}
    return cancelled | {_text(loop.iter) for loop in _walk_own(function) if isinstance(loop, LOOPS) and _names(loop.target) & cancelled}


def _awaited_names(node: ast.Try) -> set[str]:
    """Names awaited in a try body, inside `asyncio.gather(*tasks)` or `wait_for(task, 5)` as well as bare."""
    return {_text(inner) for statement in node.body for awaiting in ast.walk(statement) if isinstance(awaiting, ast.Await)
            for inner in ast.walk(awaiting.value) if isinstance(inner, (ast.Name, ast.Attribute))}


def _swallowed_cancellation(tree: ast.Module) -> Iterator[tuple]:
    """In a coroutine, cancellation has to propagate unless this code cancelled those tasks itself, or asyncio.timeout(),
    TaskGroup and shutdown can't stop it. A synchronous `except CancelledError` around a concurrent.futures result is fine."""
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)):
        cancelled = _cancelled_by(function)
        # Waiting for tasks this code cancelled itself is how it lets them finish, so that handler is fine.
        tries = [node for node in _walk_own(function) if isinstance(node, ast.Try) and not _awaited_names(node) & cancelled]
        for handler in (handler for node in tries for handler in node.handlers if _catches_cancellation(handler) and _swallows(handler)):
            yield "swallowed-cancellation", handler.lineno, "This catches cancellation and doesn't re-raise it, so asyncio.timeout() and TaskGroup around this code can't tell it was cancelled, and code that carries on after it doesn't stop. Clean up, then raise, or call uncancel() if suppressing it is truly intended.", {}


def _nested_event_loop(tree: ast.Module) -> Iterator[tuple]:
    """asyncio.run inside a coroutine raises, because a loop is already running there. The caller has to await instead."""
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)):
        for node in _calls(_walk_own(function)):
            if _text(node.func) == "asyncio.run" or _method(node) == "run_until_complete":
                yield "nested-event-loop", node.lineno, f"{_text(node.func)}() inside a coroutine fails, since its event loop is already running. Await the coroutine instead.", {}


# ---------------------------------------------------------------- values that differ between processes, clocks and machines

def _plainly_an_int(argument: ast.AST) -> bool:
    """hash() of an int is the int itself, the same in every process."""
    if isinstance(argument, ast.Constant) or (isinstance(argument, ast.Call) and _text(argument.func) in ("int", "len", "id", "ord")):
        return True
    return isinstance(argument, ast.Attribute) and argument.attr == "int"


def _in_process(bound: ast.AST) -> bool:
    """`% len(self.locks)` stripes a structure this object holds, where a per-process hash is fine. `% len(nodes)` over
    servers or shards is the bug itself, so only a length of something on self counts."""
    return any(isinstance(node, ast.Call) and _text(node.func) == "len" and node.args and _text(node.args[0]).startswith("self.") for node in ast.walk(bound))


def _salted_hash(tree: ast.Module) -> Iterator[tuple]:
    """hash() of str or bytes changes with each process, so a bucket picked from it, by % n or by & (n - 1), differs between workers and restarts."""
    for node in ast.walk(tree):
        left = node.left if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.BitAnd)) else None
        hashed = left.args[0] if isinstance(left, ast.Call) and _text(left.func) == "hash" and left.args else None
        if hashed is not None and not _plainly_an_int(hashed) and _text(hashed) != "self" and not _in_process(node.right):
            yield "salted-hash-partition", node.lineno, "hash() of a string or bytes is salted per process, so another worker, or this one after a restart, picks a different bucket. Use a stable hash such as zlib.crc32 or hashlib for anything shared or stored.", {}


def _is_wall_clock(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _text(node.func) == "time.time" and not node.args


def _is_wall_clock_anchor(value: ast.AST) -> bool:
    """`start = time.time()` or `deadline = time.time() + timeout`."""
    return _is_wall_clock(value) or (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add) and (_is_wall_clock(value.left) or _is_wall_clock(value.right)))


def _loop_tests(loop: ast.AST) -> list:
    tests = [loop.test] if isinstance(loop, ast.While) else []
    return tests + [inner.test for statement in loop.body for inner in ast.walk(statement) if isinstance(inner, ast.If)]


def _waits_on(test: ast.AST, anchors: set[str]) -> bool:
    return any(isinstance(node, ast.Compare) and _names(node) & anchors and any(_is_wall_clock(inner) for inner in ast.walk(node)) for node in ast.walk(test))


def _wall_clock_waits(tree: ast.Module) -> Iterator[tuple]:
    """A deadline or elapsed time taken from time.time() jumps when the clock is set or synced, so a wait ends early or never."""
    for scope in [tree, *_functions(tree)]:
        anchors = _assigned_from(scope, _is_wall_clock_anchor)
        loops = [node for node in _walk_own(scope) if isinstance(node, (ast.While, *LOOPS))] if anchors else []
        test = next((test for loop in loops for test in _loop_tests(loop) if _waits_on(test, anchors)), None)
        if test is not None:
            yield "wall-clock-wait", test.lineno, "This wait measures time with time.time(), which jumps when the system clock is set or synced, so it can end early or never. Use time.monotonic() for deadlines and elapsed time.", {}


def _shadows_stdlib(path: str) -> Iterator[tuple]:
    folder, _, name = path.replace("\\", "/").rpartition("/")
    stem = name[:-3] if name.endswith(".py") else ""
    if stem in STDLIB_NAMES and folder in _SCRIPT_FOLDERS:
        yield "stdlib-shadowed", 1, f"This file is named like the standard library's `{stem}`, so a script run from {folder or 'the top folder'} imports this instead, and so does anything that script imports. Rename it.", {}


# ---------------------------------------------------------------- decorators, GPUs, foreign functions, subprocesses

def _wrapper_without_wraps(outer: ast.AST) -> ast.AST | None:
    """The nested function a decorator returns, when it calls the decorated function and isn't wrapped with functools.wraps."""
    if not outer.args.args or any(_text(node.func).endswith("update_wrapper") for node in _calls(_walk_own(outer))):
        return None
    wrapped = outer.args.args[0].arg
    returned = {statement.value.id for statement in outer.body if isinstance(statement, ast.Return) and isinstance(statement.value, ast.Name)}
    return next((inner for inner in outer.body if isinstance(inner, FUNCTIONS) and inner.name in returned and _bare_wrapper(inner, wrapped)), None)


def _bare_wrapper(inner: ast.AST, wrapped: str) -> bool:
    """Takes *args and **kwargs, calls the decorated function, and has no functools.wraps."""
    forwards = bool(inner.args.vararg and inner.args.kwarg)
    calls_it = any(isinstance(node.func, ast.Name) and node.func.id == wrapped for node in _calls(ast.walk(inner)))
    return forwards and calls_it and not any("wraps" in _text(decorator) for decorator in inner.decorator_list)


def _wraps_nothing(tree: ast.Module) -> Iterator[tuple]:
    """A decorator that returns its wrapper without functools.wraps hides the wrapped function's name, docstring and signature."""
    for outer in _functions(tree):
        inner = _wrapper_without_wraps(outer)
        if inner is not None:
            yield "unwrapped-decorator", inner.lineno, f"{outer.name} returns {inner.name} without functools.wraps, so whatever it decorates loses its name, docstring and signature, which tools that read signatures depend on.", {}


def _is_timer_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _text(node.func) in _TIMERS


def _timed_spans(function: ast.AST) -> list:
    """Differences of two timer reads, such as `time.perf_counter() - start`."""
    timers = _assigned_from(function, _is_timer_call)
    return [node for node in _walk_own(function) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
            and all(_is_timer_call(side) or (isinstance(side, ast.Name) and side.id in timers) for side in (node.left, node.right))]


def _unsynced_gpu_timing(tree: ast.Module, text: str) -> Iterator[tuple]:
    """CUDA and JAX run asynchronously, so reading a timer without synchronizing times the launch, not the work."""
    for function in _functions(tree) if _USES_A_GPU.search(text) else ():
        spans = _timed_spans(function)
        source = _text(function) if spans else ""
        if spans and _GPU_WORK.search(source) and not _SYNCS.search(source):
            yield "gpu-timing-unsynced", spans[0].lineno, f"{function.name} times GPU work without synchronizing, so it measures how long the work took to launch. Call torch.cuda.synchronize() (or block_until_ready() in JAX) before each timer read, or use CUDA events.", {}


def _discarded_exit_status(tree: ast.Module) -> Iterator[tuple]:
    """subprocess.run and subprocess.call don't raise on failure, so a statement that drops the result hides a failed command.
    os.system is left out: called as a statement it's mostly a deliberate fire-and-forget, such as `os.system("")` on Windows."""
    for node in ast.walk(tree):
        call = node.value if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) else None
        keywords = {keyword.arg for keyword in call.keywords} if call else {"check"}
        if call and _text(call.func) in ("subprocess.run", "subprocess.call") and not keywords & {"check", None}:
            yield "ignored-error", node.lineno, f"{_text(call.func)}() returns the exit status and doesn't raise on failure, so a failed command here passes silently. Pass check=True, or read the result.", {}


def _nan_equality(tree: ast.Module) -> Iterator[tuple]:
    """NaN is unequal to everything, itself included, so == against it is always False and != always True."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops) and any(_text(side) in _NAN for side in (node.left, *node.comparators)):
            yield "nan-comparison", node.lineno, "Nothing equals NaN, not even NaN, so this comparison never changes its answer. Use math.isnan(), or isna() on arrays and frames.", {}


def _compile_in_loop(tree: ast.Module) -> Iterator[tuple]:
    """Compiling inside a loop pays the compile cost on every pass, and a fresh wrapper each time throws away its cache."""
    for loop in (node for node in ast.walk(tree) if isinstance(node, (*LOOPS, ast.While))):
        found = next((node for statement in loop.body if not isinstance(statement, (*FUNCTIONS, ast.ClassDef))
                      for node in _calls(_walk_own(statement)) if _text(node.func) in _COMPILERS), None)
        if found is not None:
            yield "compile-in-loop", found.lineno, f"{_text(found.func)}() runs on every pass of this loop, so each pass pays to compile again. Compile once, outside it.", {}
            return


def _pool_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """How this module can name a process pool: the bare names it imported, and the module aliases it calls through.
    Only the standard library's pools count, since `multiprocess` and `loky` pickle with dill and cloudpickle, which take lambdas."""
    bare, modules = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("multiprocessing", "multiprocessing.pool", "concurrent.futures"):
            bare.update(alias.asname or alias.name for alias in node.names if alias.name in ("Pool", "ProcessPoolExecutor"))
        elif isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name in ("multiprocessing", "concurrent.futures"))
    return bare, modules


def _pools_in(scope: ast.AST, is_pool: Callable[[ast.AST], bool]) -> set[str]:
    """Names this scope gives a process pool, by assignment or by `with ... as`."""
    held = {item.optional_vars.id for item in _walk_own(scope) if isinstance(item, ast.withitem) and is_pool(item.context_expr) and isinstance(item.optional_vars, ast.Name)}
    return _assigned_from(scope, is_pool) | held


def _sent_to_pool(call: ast.Call, pools: set[str]) -> ast.AST | None:
    """What a call like `pool.map(fn, xs)` hands the pool to run, if the receiver is a pool."""
    return call.args[0] if call.args and isinstance(call.func, ast.Attribute) and _text(call.func.value) in pools else None


def _lambda_to_process_pool(tree: ast.Module) -> Iterator[tuple]:
    """Process pools pickle what they run, and a lambda or a function defined inside another can't be pickled."""
    bare, modules = _pool_names(tree)
    roots = {module.split(".")[0] for module in modules}

    def is_pool(value: ast.AST) -> bool:
        called = _text(value.func) if isinstance(value, ast.Call) else ""
        return called in bare or (called.endswith((".Pool", ".ProcessPoolExecutor")) and called.split(".")[0] in roots)

    for scope in [tree, *_functions(tree)] if bare or roots else ():
        pools = _pools_in(scope, is_pool)
        nested = {node.name for node in scope.body if isinstance(node, FUNCTIONS)} if isinstance(scope, FUNCTIONS) else set()
        for node, sent in ((node, _sent_to_pool(node, pools)) for node in _calls(_walk_own(scope)) if pools):
            if isinstance(sent, ast.Lambda) or (isinstance(sent, ast.Name) and sent.id in nested):
                yield "process-pool-unpicklable", node.lineno, "A process pool pickles the function it runs, and a lambda or a function defined inside another can't be pickled, so this fails when it runs. Use a function defined at module level.", {}


def _declared_foreign(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Functions given argtypes or restype, and libraries whose functions are declared through getattr, which hides their names."""
    declared, dynamic = set(), set()
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.Assign)):
        for target in (target for target in node.targets if isinstance(target, ast.Attribute) and target.attr in ("argtypes", "restype")):
            declared.add(_text(target.value))
            if isinstance(target.value, ast.Call) and _text(target.value.func) == "getattr" and target.value.args:
                dynamic.add(_text(target.value.args[0]))
    return declared, dynamic


def _handles_cut_short(tree: ast.Module, libraries: set[str]) -> Iterator[tuple]:
    """A function given argtypes but no restype still returns a C int. When what it returns is kept and handed back to the library, it's a
    handle or pointer, and on a 64-bit build its top half is gone."""
    argtypes, restypes = set(), set()
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.Assign)):
        for target in (target for target in node.targets if isinstance(target, ast.Attribute)):
            (argtypes if target.attr == "argtypes" else restypes if target.attr == "restype" else set()).add(_text(target.value))
    foreign = [node for node in _calls(ast.walk(tree)) if isinstance(node.func, ast.Attribute) and _text(node.func.value) in libraries]
    passed = {_text(argument) for node in foreign for argument in node.args}
    reported = set()
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.value, ast.Call)):
        name = _text(node.value.func)
        if node.value in foreign and name in argtypes - restypes - reported and _text(node.targets[0]) in passed:
            reported.add(name)
            yield ("ctypes-untyped", node.lineno, f"{name} has argtypes but no restype, so ctypes returns its result as a C int, and the handle kept here is "
                   "cut to 32 bits before it goes back to the library. Set restype, such as c_void_p.", {})


def _untyped_foreign_calls(tree: ast.Module) -> Iterator[tuple]:
    """ctypes assumes every argument and return value is a C int unless told otherwise, so a pointer or a 64-bit value is cut short."""
    declared, dynamic = _declared_foreign(tree)
    libraries = _assigned_from(tree, lambda value: isinstance(value, ast.Call) and bool(_CTYPES_LIBRARY.match(_text(value.func)))) - dynamic
    # No arguments and a discarded result can't be truncated, as in `lib.release_resources()`.
    harmless = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and not node.value.args}
    seen = set()
    for node in _calls(ast.walk(tree)) if libraries else ():
        name = _text(node.func)
        if isinstance(node.func, ast.Attribute) and _text(node.func.value) in libraries and id(node) not in harmless and name not in declared | seen:
            seen.add(name)
            yield "ctypes-untyped", node.lineno, f"{name} is called with no argtypes or restype, so ctypes treats its arguments and result as C int, which truncates pointers and 64-bit values. Declare both.", {}
    if libraries:
        yield from _handles_cut_short(tree, libraries)


# ---------------------------------------------------------------- effects that happen twice, or for anyone

def _creates_a_row(call: ast.Call) -> bool:
    receiver = _text(call.func.value) if isinstance(call.func, ast.Attribute) else ""
    method = _method(call)
    if method in ("create", "bulk_create"):
        return receiver.endswith(".objects")
    if method in ("insert", "insert_one", "insert_many"):
        return True
    return method == "add" and bool(_SESSIONS.search(receiver))


def _is_absence_check(test: ast.AST) -> bool:
    negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
    compared = any(isinstance(op, (ast.Is, ast.Eq)) for inner in ast.walk(test) if isinstance(inner, ast.Compare) for op in inner.ops)
    return (negated or compared) and bool(_EXISTS.search(_text(test)))


# Code that catches the conflict a unique constraint raises, or asks the database to resolve it, has the constraint the check needs.
_HANDLES_A_CONFLICT = re.compile(r"IntegrityError|UniqueViolation|DuplicateKey|on_conflict|ON CONFLICT|get_or_create|update_or_create|upsert", re.I)
_READS_A_ROW = re.compile(r"\.(?:objects|query)\b.{0,200}?\.(?:filter|filter_by|get|exists|first|count)\(|\b(?:scalar|scalars|execute|query)\(\s*select\(|\.find_one\(|\.count_documents\(")
_CHECK_THEN_INSERT = ("This checks that the row is missing and then creates it, so two requests at once can both create it. Back it with a unique "
                      "constraint and handle the conflict, or use get_or_create or an upsert.")


def _exits(statements: list) -> bool:
    last = statements[-1] if statements else None
    return isinstance(last, (ast.Raise, ast.Return)) or (isinstance(last, ast.Expr) and isinstance(last.value, ast.Call) and _text(last.value.func).rsplit(".", 1)[-1] == "abort")


def _tests_the_row(test: ast.AST, reads: set[str]) -> bool:
    """`taken`, `existing is not None` or `count > 0`, for a name holding a read. `wallet.balance < amount` tests a field of the row, not that it's there."""
    if isinstance(test, ast.Name):
        return test.id in reads
    if isinstance(test, ast.BoolOp):
        return any(_tests_the_row(value, reads) for value in test.values)
    return (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id in reads and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.IsNot, ast.Gt, ast.NotEq, ast.GtE)) and isinstance(test.comparators[0], ast.Constant))


def _is_presence_check(test: ast.AST, reads: set[str]) -> bool:
    """`if db.scalar(select(...)):`, or `if taken:` where taken holds such a read. Not negated: `if not exists: create` is the other shape."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return False
    text = _text(test)
    return bool(_EXISTS.search(text) or _READS_A_ROW.search(text)) or _tests_the_row(test, reads)


_MODEL_NAMES = re.compile(r"\b[A-Z]\w*\b|\b\w+(?=\.(?:find_one|count_documents|insert_one|insert_many|insert)\()")


def _created_models(call: ast.Call, bound: dict[str, ast.AST]) -> set[str]:
    """What a create writes to: `Post.objects.create` is Post, `db.add(user)` is whatever class `user` was built from, `db.users.insert_one`
    is users. Empty when it can't be told."""
    method, receiver = _method(call), call.func.value if isinstance(call.func, ast.Attribute) else None
    if method in ("create", "bulk_create") and receiver is not None:
        return {_text(receiver).rsplit(".", 1)[0].rsplit(".", 1)[-1]}
    if method in ("insert", "insert_one", "insert_many") and receiver is not None:
        return {_text(receiver).rsplit(".", 1)[-1]}
    made = call.args[0] if call.args else None
    if isinstance(made, ast.Name):
        made = bound.get(made.id)
    return {_text(made.func).rsplit(".", 1)[-1]} if isinstance(made, ast.Call) else set()


def _exit_then_create(function: ast.AST) -> Iterator[ast.If]:
    """`if <row exists>: raise Conflict` followed by an insert into the same model or table: the same race as creating inside
    `if not exists:`. A check on one table before writing another, as a ban check before a comment, isn't this."""
    blocks = [function.body] + [getattr(node, field) for node in _walk_own(function) for field in ("body", "orelse", "finalbody")
                                if isinstance(getattr(node, field, None), list) and not isinstance(node, (*FUNCTIONS, ast.ClassDef))]
    if not any(isinstance(statement, ast.If) and not statement.orelse and _exits(statement.body) for block in blocks for statement in block):
        return
    reads = _assigned_from(function, lambda value: bool(_EXISTS.search(_text(value)) or _READS_A_ROW.search(_text(value))))
    bound = {node.targets[0].id: node.value for node in _walk_own(function) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    for block in blocks:
        creates = [(index, call) for index, later in enumerate(block) for call in _calls(ast.walk(later)) if _creates_a_row(call)]
        if not creates:
            continue
        for index, statement in enumerate(block):
            if isinstance(statement, ast.If) and not statement.orelse and _exits(statement.body) and _is_presence_check(statement.test, reads):
                checked_text = _text(statement.test) + " " + " ".join(_text(bound[name]) for name in _names(statement.test) & reads if name in bound)
                checked = set(_MODEL_NAMES.findall(checked_text))
                if any(at > index and _created_models(call, bound) & checked for at, call in creates):
                    yield statement
                    break


def _check_then_create(tree: ast.Module) -> Iterator[tuple]:
    """Checking that a row is absent and then inserting it lets two requests both pass the check. Only a unique constraint stops that."""
    functions = list(_functions(tree))
    verdicts: dict[int, bool] = {}
    enclosing: dict[int, ast.AST] = {}

    def function_of(node: ast.If) -> ast.AST | None:
        if not enclosing:  # built the first time an absence check turns up, which most files never reach
            enclosing.update({id(inner): function for function in functions for inner in _walk_own(function) if isinstance(inner, ast.If)})
        return enclosing.get(id(node))

    def handles_conflict(function: ast.AST | None) -> bool:  # read only where a candidate turned up, since it unparses the function
        if function is None:
            return False
        if id(function) not in verdicts:
            verdicts[id(function)] = bool(_HANDLES_A_CONFLICT.search(_text(function)))
        return verdicts[id(function)]

    for node in (node for node in ast.walk(tree) if isinstance(node, ast.If) and _is_absence_check(node.test)):
        if any(_creates_a_row(call) for statement in node.body for call in _calls(ast.walk(statement))) and not handles_conflict(function_of(node)):
            yield "check-then-insert", node.lineno, _CHECK_THEN_INSERT, {}
    for function in functions:
        for node in _exit_then_create(function):
            if not handles_conflict(function):
                yield "check-then-insert", node.lineno, _CHECK_THEN_INSERT, {}


def _is_retried(function: ast.AST) -> bool:
    """A retry decorator, or a Celery task that retries itself: `autoretry_for=` on its decorator, or `self.retry(...)` in its body."""
    for decorator in function.decorator_list:
        if _RETRY_DECORATOR.search(_text(decorator.func if isinstance(decorator, ast.Call) else decorator)):
            return True
        if isinstance(decorator, ast.Call) and any(keyword.arg == "autoretry_for" for keyword in decorator.keywords):
            return True
    return any(isinstance(node, ast.Call) and _text(node.func) == "self.retry" for node in _walk_own(function))


def _retried_effects(tree: ast.Module) -> Iterator[tuple]:
    """A retry library repeats the whole call, so an effect that already happened before the error happens again."""
    for function in _functions(tree):
        source = _text(function) if _is_retried(function) else ""
        effect = _NOT_REPEATABLE.search(source)
        if effect and not _IDEMPOTENT.search(source):
            yield "retry-not-idempotent", function.lineno, f"{function.name} is retried, and it calls {effect.group(0).rstrip('(')} with no idempotency key, so a failure after that effect lands repeats it. Pass a key the far side deduplicates on, or retry only reads.", {}


def _receives_posts(decorator: ast.AST) -> bool:
    """A route that accepts POST: `@app.post`, or `@app.route` listing POST in its methods."""
    method = _text(decorator.func).rsplit(".", 1)[-1]
    if method in ("post", "api_route"):
        return True
    methods = next((keyword.value for keyword in decorator.keywords if keyword.arg == "methods"), None)
    return method == "route" and methods is not None and "POST" in _text(methods).upper()


def _webhook_route(function: ast.AST) -> bool:
    return any(isinstance(decorator, ast.Call) and decorator.args and isinstance(decorator.args[0], ast.Constant)
               and "webhook" in str(decorator.args[0].value).lower() and _receives_posts(decorator) for decorator in function.decorator_list)


def _unverified_webhooks(tree: ast.Module) -> Iterator[tuple]:
    """A webhook URL is public, so a handler that doesn't check the sender's signature acts on whatever anyone posts."""
    for function in _functions(tree):
        if _webhook_route(function) and not _VERIFIES.search(_text(function)):
            yield "webhook-unverified", function.lineno, f"{function.name} receives a webhook and never checks its signature, so anyone who finds the URL can post events. Verify the signature over the raw body, and reject stale or repeated events.", {}


def _is_route(function: ast.AST) -> bool:
    return any(ROUTE_DECORATOR_NAME.search(_text(decorator.func if isinstance(decorator, ast.Call) else decorator)) for decorator in function.decorator_list)


def _sends_a_trace(node: ast.AST, in_route: bool) -> bool:
    if isinstance(node, ast.Call) and _RESPONDS.search(_text(node.func)):
        return bool(_TRACEBACK.search(_text(node)))
    return isinstance(node, ast.Return) and in_route and node.value is not None and bool(_TRACEBACK.search(_text(node.value)))


def _error_details_exposed(tree: ast.Module) -> Iterator[tuple]:
    """A stack trace in a response shows an outsider file paths, queries and sometimes secrets."""
    for function in _functions(tree):
        in_route = _is_route(function)
        found = next((node for node in _walk_own(function) if _sends_a_trace(node, in_route)), None)
        if found is not None:
            yield "error-details-exposed", found.lineno, "This sends a stack trace back to the caller, which shows an outsider file paths, queries and sometimes secrets. Log it, and return a short message with an id to look it up.", {}


def _reflected_cors(tree: ast.Module, text: str) -> Iterator[tuple]:
    """flask-cors with credentials and no origins of its own reflects whatever origin asks, so every site can act as the user.
    Origins given as an argument, through resources=, or in app.config's CORS_ORIGINS are a list someone chose."""
    for node in _calls(ast.walk(tree)) if "CORS_ORIGINS" not in text else ():
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        credentials = keywords.get("supports_credentials")
        if (_text(node.func).rsplit(".", 1)[-1] == "CORS" and isinstance(credentials, ast.Constant) and credentials.value is True
                and not {"origins", "resources", None} & set(keywords)):  # None is a **kwargs that could carry them
            yield "permissive-cors", node.lineno, "CORS with credentials and no origins reflects whatever site asks, so any page can make requests as the signed-in user. List the origins you serve.", {"severity": "high"}


def _collected_to_driver(tree: ast.Module, text: str) -> Iterator[tuple]:
    """Spark's toPandas() and collect() pull a whole distributed result into the driver's memory."""
    for node in _calls(ast.walk(tree)) if re.search(r"\bpyspark\b", text) else ():
        if _method(node) in ("toPandas", "collect") and not node.args:
            yield "materialize-all", node.lineno, f"{_method(node)}() pulls the whole distributed result into the driver's memory. Write it out from the workers, or reduce it first.", {}


# Rules for code tests run too, and the rest. Test fakes often keep a class-level list on purpose, to record calls across
# instances, and tests of numeric code compare with NaN on purpose to pin down its behavior.
_EVERYWHERE = (_late_binding, _mutated_while_walked, _nested_event_loop, _lambda_to_process_pool)
_SHIPPED_ONLY = (_nan_equality, _class_shared_mutables, _swallowed_cancellation, _salted_hash, _wall_clock_waits, _wraps_nothing,
                 _discarded_exit_status, _compile_in_loop, _untyped_foreign_calls, _check_then_create, _retried_effects,
                 _unverified_webhooks, _error_details_exposed)


def findings(tree: ast.Module, path: str, is_test: bool, text: str = "") -> list[tuple]:
    """(rule, line, message, overrides) for one parsed module. A rule that breaks on unusual code loses only its own findings:
    the file's other findings, including serious ones from older rules, still stand."""
    rules = [*_EVERYWHERE, *(() if is_test else _SHIPPED_ONLY)]
    found = list(_shadows_stdlib(path))
    for rule in rules:
        try:
            found += list(rule(tree))
        except (RecursionError, ValueError, AttributeError, TypeError):  # occam: ignore[swallowed-exception] one rule's miss, never the file's
            continue
    if not is_test:
        for rule in (_unsynced_gpu_timing, _collected_to_driver, _reflected_cors):
            try:
                found += list(rule(tree, text))
            except (RecursionError, ValueError, AttributeError, TypeError):  # occam: ignore[swallowed-exception] as above
                continue
    return found
