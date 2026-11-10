"""Python rules for what a program holds or shares: clients, locks, queues, files, caches, and what tests reach outside themselves.

docs/quality-catalog.md says which failure each answers. Like rules_py_semantics, none of them is high severity and high confidence
at once, so none of them sends an agent back: they show in `scan`, `gate` and audits.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

from .py_helpers import ROUTE_DECORATOR, _decorator_names, _dotted, _walk_own as _own

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
# Mock methods that look like assertions and aren't: a Mock answers any name with a truthy Mock, so these pass whatever happened.
_NOT_ASSERTIONS = {"called_once_with", "called_with", "called_once", "not_called", "has_calls", "any_call", "awaited_once_with", "awaited_with"}
# Calls that return something lazy, which reads its argument only when iterated.
_LAZY = {"map", "filter", "zip", "enumerate", "iter", "reversed", "csv.reader", "csv.DictReader", "itertools.islice", "itertools.chain", "islice"}
_LOCK = re.compile(r"(?:^|[._])(?:lock|rlock|mutex)$", re.I)
_USER = re.compile(r"^(?:request\.user|request\.state\.user|current_user|flask_login\.current_user|g\.user|g\.current_user|request\.tenant|g\.tenant)$")
_CACHES = {"cache", "lru_cache", "functools.cache", "functools.lru_cache", "cached", "cachetools.cached"}
# Clients that hold connections, sessions or pools, meant to be made once and shared.
_CLIENTS = {"requests.Session", "requests.session", "httpx.Client", "httpx.AsyncClient", "aiohttp.ClientSession", "urllib3.PoolManager",
            "boto3.client", "boto3.resource", "boto3.session.Session", "create_engine", "sqlalchemy.create_engine", "create_async_engine",
            "psycopg2.connect", "psycopg.connect", "pymongo.MongoClient", "MongoClient", "redis.Redis", "redis.StrictRedis",
            "openai.OpenAI", "anthropic.Anthropic", "Elasticsearch"}
_IO_CALLS = re.compile(r"^(?:requests|httpx|urllib\.request|subprocess|boto3|socket)\.\w+$|^(?:open|urlopen)$|\.(?:execute|fetchall|fetchone|urlopen|read_text|read_bytes)$")
_QUEUES = {"queue.Queue", "Queue", "asyncio.Queue", "multiprocessing.Queue", "queue.LifoQueue", "queue.PriorityQueue", "queue.SimpleQueue", "SimpleQueue"}
_REPLACES = re.compile(r"\bos\.(?:replace|rename)\(|\.(?:replace|rename)\(\s*\w|NamedTemporaryFile|mkstemp|atomic", re.I)
_HTTP_CALL = re.compile(r"^(?:requests|httpx)\.(?:get|post|put|patch|delete|head|request)$|^(?:urllib\.request\.)?urlopen$")
_LOCAL_URL = re.compile(r"^\w+://(?:localhost|127\.|0\.0\.0\.0|\[::1\]|testserver|[\w.-]*\.(?:test|invalid|example|local|localhost)(?:[:/]|$)|example\.(?:com|org|net)(?:[:/]|$))", re.I)
_FAKERS = r"(?:responses|respx|requests_mock|vcr|pytest_httpserver|httpretty|aioresponses|pytest_recording|betamax|pook)\b"
_FAKES_NETWORK = re.compile(rf"^[ \t]*(?:from[ \t]+{_FAKERS}|import[ \t]+(?:[\w.]+[ \t]*,[ \t]*)*{_FAKERS})|"
                            r"(?:patch|mocker\.patch)\(\s*['\"](?:requests|httpx|urllib)", re.M)
# Calls that listen, as opposed to a client naming the port it connects to.
_SERVES = {"run", "serve", "serve_forever", "listen", "start_server", "make_server", "create_server", "run_app", "bind"}
_POOL = re.compile(r"(?:^|[._])(?:executor|pool)$", re.I)
_QUERYSET = re.compile(r"\.objects\.(?:all|filter|exclude|order_by)\(")
_PREFETCHED = re.compile(r"\b(?:select_related|prefetch_related|values|values_list|only)\(")
# Fixtures and markers that fake or announce the network: pytest-httpx, requests-mock, respx, vcr, and tests marked as integration.
_FAKE_FIXTURES = re.compile(r"\b(?:httpx_mock|requests_mock|respx_mock|aioresponses|vcr_cassette)\b|mark\.(?:vcr|integration|network|e2e|online|live)\b")
_INTEGRATION_FOLDER = re.compile(r"(?:^|/)(?:integration|e2e|functional|system|live|smoke)(?:_tests?)?/", re.I)
_RANDOM_CALL = re.compile(r"^(?:random\.(?:random|randint|choice|choices|sample|shuffle|uniform|randrange|gauss)|(?:np|numpy)\.random\.(?!default_rng$|RandomState$|Generator$|SeedSequence$|PCG64$)\w+)$")


def _called(node: ast.AST) -> str:
    return _dotted(node.func) if isinstance(node, ast.Call) else ""


def _not_assertions(tree: ast.Module) -> Iterator[tuple]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _NOT_ASSERTIONS:
            yield ("mock-assert-typo", node.lineno, f"`.{node.func.attr}(...)` isn't an assertion. A Mock answers any name with a truthy Mock, so this passes "
                   f"whatever happened. Use `assert_{node.func.attr}(...)`.", {})


def _lazy_after_close(tree: ast.Module) -> Iterator[tuple]:
    """Returning a lazy reader from inside `with` hands back something that reads a file or connection the `with` has just closed."""
    for function in (node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)):
        for block in (node for node in _own(function) if isinstance(node, ast.With)):
            held = {item.optional_vars.id for item in block.items if isinstance(item.optional_vars, ast.Name)}
            for returned in (node for node in _run_here(block.body) if isinstance(node, ast.Return)):
                reads = _iterated(returned.value) & held
                if reads:
                    yield ("lazy-after-close", returned.lineno, f"This returns a lazy reader of `{min(reads)}`, which the `with` closes as the function returns, "
                           "so iterating it later fails or reads nothing. Build a list inside the block, or yield from inside it.", {})


def _iterated(value: ast.AST | None) -> set[str]:
    """Names a lazy expression iterates when it's consumed: `line for line in f` and `map(str.strip, f)` do, and `f.read().split()` already did."""
    if isinstance(value, ast.GeneratorExp):
        return {value.generators[0].iter.id} if isinstance(value.generators[0].iter, ast.Name) else set()
    if _called(value) in _LAZY:
        return {argument.id for argument in value.args if isinstance(argument, ast.Name)}
    return set()


def _run_here(block: list) -> Iterator[ast.AST]:
    """The nodes a block runs itself, not those of the functions or classes it defines, which run at another time."""
    for statement in block:
        if not isinstance(statement, (*FUNCTIONS, ast.ClassDef)):
            yield statement
            yield from _own(statement)


def _within(scope: ast.AST) -> Iterator[ast.AST]:
    """A module's or a class's own nodes, not those of classes inside it, whose `self._lock` is a different object."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.ClassDef):
            stack.extend(ast.iter_child_nodes(node))


def _lock_name(item: ast.withitem) -> str | None:
    text = _dotted(item.context_expr.func if isinstance(item.context_expr, ast.Call) else item.context_expr)
    return text if text and _LOCK.search(text) else None


def _locks(tree: ast.Module) -> Iterator[tuple]:
    """Two locks taken in both orders deadlock when two threads meet, and a thread lock held across an await blocks the loop's thread."""
    for scope in [tree, *(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))]:
        yield from _locks_in(scope)


def _locks_in(scope: ast.AST) -> Iterator[tuple]:
    seen: dict[tuple[str, str], int] = {}
    for outer in (node for node in _within(scope) if isinstance(node, ast.With)):
        names = [name for name in map(_lock_name, outer.items) if name]
        for name in names:
            for inner in (node for node in _run_here(outer.body) if isinstance(node, ast.With)):
                for other in filter(None, map(_lock_name, inner.items)):
                    if other != name:
                        seen.setdefault((name, other), inner.lineno)
            awaited = next((node for node in _run_here(outer.body) if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith))), None)
            if awaited is not None:
                yield ("await-under-thread-lock", awaited.lineno, f"This awaits while holding `{name}` in a plain `with`. Another coroutine that wants it blocks the "
                       "event loop's only thread, and that deadlocks. Use asyncio.Lock with `async with`, or release it before awaiting.", {})
    for (first, second), line in sorted(seen.items(), key=lambda item: item[1]):
        if (second, first) in seen and (first, second) < (second, first):
            yield ("lock-order", max(line, seen[(second, first)]), f"`{first}` and `{second}` are taken in both orders here, so two threads can each hold one "
                   "and wait for the other forever. Always take them in one order.", {})


def _cache_reads_user(tree: ast.Module) -> Iterator[tuple]:
    for function in (node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)):
        if not set(_decorator_names(function)) & _CACHES:
            continue
        names = (_dotted(node) for node in _own(function) if isinstance(node, (ast.Attribute, ast.Name)))
        who = next((name for name in names if _USER.match(name)), None)
        if who:
            yield ("cache-reads-user", function.lineno, f"{function.name} is cached by its arguments, but reads `{who}`, which isn't one, so one user's result "
                   "is served to the next. Pass the user or tenant in as an argument, or don't cache it.", {})


def _is_route(function: ast.AST) -> bool:
    return any(name.rsplit(".", 1)[-1] in ROUTE_DECORATOR and "." in name for name in _decorator_names(function))


def _clients_per_call(tree: ast.Module, is_test: bool) -> Iterator[tuple]:
    """A client made per item or per request opens a new connection pool each time and throws it away."""
    if is_test:
        return
    # Over items, not `while`, which is how a worker reconnects after a failure.
    # Over items, not a fixed `range(5)`, which is a bounded retry like `while`. `range(len(urls))` is over items.
    places = [(loop, "loop") for loop in ast.walk(tree) if isinstance(loop, (ast.For, ast.AsyncFor)) and not _is_retry_count(loop.iter)]
    places += [(function, "request handler") for function in ast.walk(tree) if isinstance(function, FUNCTIONS) and _is_route(function)]
    reported = set()
    for place, kind in places:
        varies = _varies_per_pass(place) if kind == "loop" else set()
        for call in (call for node in _own(place) for call in _made_here(node)):
            per_target = varies & {node.id for node in ast.walk(call) if isinstance(node, ast.Name)}  # one client per region or URL is the point
            if isinstance(call, ast.Call) and _called(call) in _CLIENTS and call.lineno not in reported and not per_target:
                reported.add(call.lineno)
                yield ("client-per-call", call.lineno, f"{_called(call)}() is made in every {kind} pass, so each one opens and drops its own connections. "
                       "Make it once at startup and share it, or reuse one passed in.", {})


def _is_retry_count(node: ast.AST) -> bool:
    return _called(node) == "range" and all(isinstance(argument, ast.Constant) and isinstance(argument.value, int) for argument in node.args)


def _varies_per_pass(loop: ast.AST) -> set[str]:
    """The loop's variables and what's assigned from them in its body, as `url = tenant_url(tenant)`."""
    varies = {node.id for node in ast.walk(loop.target) if isinstance(node, ast.Name)}
    for _ in range(3):  # a short chain of derived values is enough
        for node in _own(loop):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) and node.value else []
            if targets and {name.id for name in ast.walk(node.value) if isinstance(name, ast.Name)} & varies:
                varies |= {name.id for target in targets for name in ast.walk(target) if isinstance(name, ast.Name)}
    return varies


def _made_here(node: ast.AST) -> list:
    """What a statement makes for itself: bound to a plain name, opened by `with`, or used at once. One stored in a dict or attribute is kept for reuse."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return [node.value]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:  # a bare `n: int` makes nothing
        return [node.value]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [item.context_expr for item in node.items]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return [node.func.value]
    return []


def _io_in_property(tree: ast.Module) -> Iterator[tuple]:
    for function in (node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)):
        if "property" in _decorator_names(function):
            call = next((node for node in _own(function) if isinstance(node, ast.Call) and _IO_CALLS.search(_called(node))), None)
            if call is not None:
                yield ("io-in-property", call.lineno, f"Reading `.{function.name}` runs {_called(call)}(), so plain attribute access can block, fail or cost a "
                       "round trip each time. Make it a method whose name says it fetches.", {})


def _unbounded_queues(tree: ast.Module, is_test: bool) -> Iterator[tuple]:
    if is_test:
        return
    made = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and _called(node.value) in _QUEUES and _dotted(node.targets[0]):
            call = node.value
            if not call.args and not any(keyword.arg == "maxsize" for keyword in call.keywords):
                made[_dotted(node.targets[0])] = node.lineno
    # A producer that runs until stopped, putting with a blocking put. A loop over a fixed input, or a crawl that feeds its own queue, isn't one.
    forever = (node for node in ast.walk(tree) if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True)
    for loop in forever:
        calls = [node for node in _own(loop) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        consumed = {_dotted(node.func.value) for node in calls if node.func.attr in ("get", "get_nowait")}  # a crawl feeds its own queue
        for node in calls:
            name = _dotted(node.func.value) if node.func.attr == "put" else ""
            if name in made and name not in consumed:
                yield ("unbounded-queue", made.pop(name), f"`{name}` has no maxsize and a loop that never stops puts into it, so a producer faster than its "
                       "consumer grows it until memory runs out. Give it a maxsize, so put waits.", {})


def _nonatomic_writes(tree: ast.Module, text: str, is_test: bool) -> Iterator[tuple]:
    """A file this module writes in place and reads back is left half-written by a crash, and the next read fails on it."""
    if is_test or _REPLACES.search(text):
        return
    writes, reads, structured, read_bare = {}, set(), set(), set()
    owner = _class_of_each_method(tree)
    # A read inside a try that handles the error treats a bad file as a cache miss, so a truncated one costs a rebuild, not an outage.
    recovered = {id(inner) for node in ast.walk(tree) if isinstance(node, ast.Try) and node.handlers for statement in node.body for inner in ast.walk(statement)}
    for scope in [tree, *(node for node in ast.walk(tree) if isinstance(node, FUNCTIONS))]:
        for node in _own(scope) if isinstance(scope, FUNCTIONS) else _module_level(scope):
            found = _file_access(node)
            if found and isinstance(found[1], ast.Constant) and str(found[1].value).startswith(("/dev/", "/proc/", "/sys/")):
                continue  # a device or kernel file, not stored state
            if found and found[0]:
                key = _file_key(found[1], scope, owner)
                writes.setdefault(key, node.lineno)
                # A local `path` in two functions may be two files, as a checkpoint directory's own file is, so only a name the module fixes counts.
                if _serializes(node) and not (isinstance(found[1], ast.Name) and isinstance(scope, FUNCTIONS) and _binds(scope, found[1].id)):
                    structured.add(key)
            elif found:
                reads.add(_file_key(found[1], scope, owner))
                if id(node) not in recovered:
                    read_bare.add(_file_key(found[1], scope, owner))
    for target, line in sorted(writes.items(), key=lambda item: item[1]):
        if target in reads:
            # A truncated JSON, pickle or YAML document never parses, so for those the next read fails for certain.
            yield ("nonatomic-state-write", line, "This file is written in place and read back by this module, so a crash mid-write leaves it truncated and the "
                   "next read fails. Write a temporary file beside it and os.replace it over the original.", {"confidence": "medium"} if target in structured and target in read_bare else {})


def _binds(function: ast.AST, name: str) -> bool:
    return any(isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets) for node in _own(function))


def _serializes(node: ast.AST) -> bool:
    """The write is a whole document in a format that has to be complete to parse: json.dump(..., fh), or write_text(json.dumps(...))."""
    return any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in _DUMPS
               and _dotted(call.func.value).split(".")[0] in _FORMATS for call in ast.walk(node))


def _class_of_each_method(tree: ast.Module) -> dict[int, int]:
    owner = {}
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        owner.update({id(method): id(cls) for method in cls.body if isinstance(method, FUNCTIONS)})
    return owner


def _file_key(target: ast.AST, scope: ast.AST, owner: dict[int, int]) -> str:
    """Which file an expression names. `STATE_FILE` is one file everywhere, a parameter is that function's own value, and `self.path` is its
    class's: two functions' `path`, or two classes' `self.path`, are two files."""
    names = {name.id for name in ast.walk(target) if isinstance(name, ast.Name)}
    parameters = {argument.arg for argument in ast.walk(scope.args) if isinstance(argument, ast.arg)} - {"self", "cls"} if isinstance(scope, FUNCTIONS) else set()
    if isinstance(target, ast.Name) and target.id in parameters:
        default = _constant_default(scope, target.id)
        if default is not None:  # `def save(state, path=STATE_PATH)` and `def load(path=STATE_PATH)` name one file
            return ast.dump(default)
    if names & parameters:
        return f"{ast.dump(target)}@{id(scope)}"
    if "self" in names:
        return f"{ast.dump(target)}@class{owner.get(id(scope))}"
    return ast.dump(target)


_OPENS_BY_NAME = {"io.open", "codecs.open", "gzip.open", "bz2.open", "lzma.open"}
_MODULES_WITH_OPEN = {"os", "io", "codecs", "gzip", "bz2", "lzma", "tarfile", "zipfile", "webbrowser", "shelve", "dbm", "sqlite3", "wave", "aifc", "Image", "h5py", "self", "cls"}
_DUMPS = {"dump", "dumps", "safe_dump"}
_FORMATS = {"json", "pickle", "yaml", "toml", "tomli_w", "tomlkit", "orjson", "ujson", "simplejson", "marshal"}


def _constant_default(function: ast.AST, parameter: str) -> ast.AST | None:
    """The module constant a parameter defaults to, as `path=STATE_PATH` does, or None."""
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    pairs = list(zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults)) + list(zip(arguments.kwonlyargs, arguments.kw_defaults))
    default = next((value for argument, value in pairs if argument.arg == parameter), None)
    return default if isinstance(default, (ast.Name, ast.Attribute)) else None


def _module_level(tree: ast.Module) -> Iterator[ast.AST]:
    stack = list(ast.iter_child_nodes(tree))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _file_access(node: ast.AST) -> tuple[bool, ast.AST] | None:
    """(written, what names the file) for `with open(x, "w")`, `with open(x)`, `x.write_text(...)` and `x.read_text()`."""
    if isinstance(node, ast.With):
        for item in node.items:
            call = item.context_expr
            if (_called(call) == "open" or _called(call) in _OPENS_BY_NAME) and call.args:
                mode = call.args[1] if len(call.args) > 1 else next((keyword.value for keyword in call.keywords if keyword.arg == "mode"), None)
                return isinstance(mode, ast.Constant) and str(mode.value).startswith("w"), _named_file(call)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "open" and _dotted(call.func.value) \
                    and _dotted(call.func.value).split(".")[0] not in _MODULES_WITH_OPEN:  # pathlib's `path.open("w")`: the file is the receiver
                mode = call.args[0] if call.args else next((keyword.value for keyword in call.keywords if keyword.arg == "mode"), None)
                return isinstance(mode, ast.Constant) and str(mode.value).startswith("w"), call.func.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("write_text", "write_bytes", "read_text", "read_bytes"):
        return node.func.attr.startswith("write"), _named_file(node.func.value)
    return None


def _named_file(node: ast.AST) -> ast.AST:
    """What a call names as its file: the path inside `open(x)` or `Path(x)`, or the expression itself."""
    if isinstance(node, ast.Call) and _called(node) in ("open", "Path", "pathlib.Path") and node.args:
        return node.args[0]
    return node


def _network_calls(tree: ast.Module, text: str) -> Iterator[tuple]:
    """A test that calls a real service fails offline or when the service changes, unless the file fakes that boundary."""
    if _FAKES_NETWORK.search(text) or _FAKE_FIXTURES.search(text):
        return
    for node in ast.walk(tree):
        url = _first_text(node) if isinstance(node, ast.Call) and _HTTP_CALL.match(_called(node)) else ""
        if re.match(r"https?://", url) and not _LOCAL_URL.match(url):
            yield ("network-in-unit-test", node.lineno, f"This test calls {url.split('/')[2]} for real, so it fails offline or when that service changes. "
                   "Fake the boundary with a library such as responses or respx, and keep real calls in marked integration tests.", {})


def _fixed_resources(tree: ast.Module) -> Iterator[tuple]:
    """A fixed port or a fixed path under /tmp collides when tests run in parallel or something else holds it."""
    for node in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        name = _called(node)
        port = _listening_port(node, name)
        if port:
            yield ("fixed-test-resource", node.lineno, f"Port {port} is fixed, so parallel runs or anything already listening there collide. Bind port 0 and read "
                   "back the port given.", {})
        path = _tmp_written(node, name)
        if path:
            yield ("fixed-test-resource", node.lineno, f"{path} is shared by every run on this machine, so parallel runs overwrite each other. Use tmp_path.", {})


def _tmp_written(call: ast.Call, name: str) -> str:
    """The fixed /tmp path of `open("/tmp/x", "w")` or `Path("/tmp/x").write_text(...)`, or "". Reading one, or expecting it missing, collides with nothing."""
    if name == "open":
        mode = call.args[1] if len(call.args) > 1 else next((keyword.value for keyword in call.keywords if keyword.arg == "mode"), None)
        written = isinstance(mode, ast.Constant) and str(mode.value)[:1] in ("w", "a", "x")
        return _first_text(call) if written and _first_text(call).startswith("/tmp/") else ""
    receiver = call.func.value if isinstance(call.func, ast.Attribute) and call.func.attr in ("write_text", "write_bytes", "mkdir", "touch") else None
    path = _first_text(receiver) if isinstance(receiver, ast.Call) and _called(receiver) in ("Path", "pathlib.Path") else ""
    return path if path.startswith("/tmp/") else ""


def _first_text(call: ast.Call) -> str:
    return call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str) else ""


def _listening_port(call: ast.Call, name: str) -> int | None:
    """The port a server or socket is told to listen on, from `port=` or an address tuple. A client naming the port it connects to isn't one."""
    if not (name.rsplit(".", 1)[-1] in _SERVES or name.endswith("Server")):
        return None
    port = next((keyword.value.value for keyword in call.keywords if keyword.arg == "port" and isinstance(keyword.value, ast.Constant)), None)
    address = call.args[0] if call.args else None
    if isinstance(address, ast.Tuple) and len(address.elts) == 2 and isinstance(address.elts[1], ast.Constant):
        port = address.elts[1].value
    return port if isinstance(port, int) and not isinstance(port, bool) and port > 0 else None


def _unseeded_random(tree: ast.Module, text: str) -> Iterator[tuple]:
    if "seed" in text or re.search(r"^[ \t]*(?:import|from)[ \t]+hypothesis\b", text, re.M):
        return
    call = next((node for node in ast.walk(tree) if isinstance(node, ast.Call) and (_RANDOM_CALL.match(_called(node)) or _called(node) in ("Faker", "faker.Faker")
                 or _called(node) in ("np.random.default_rng", "numpy.random.default_rng", "np.random.RandomState", "numpy.random.RandomState") and not node.args)), None)
    if call is not None:
        yield ("unseeded-random-test", call.lineno, f"This test draws from {_called(call)} with no seed in the file, so a failure can't be replayed. Seed it, "
               "or print the seed on failure, unless a conftest already does.", {})


def _dense_expressions(tree: ast.Module) -> Iterator[tuple]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            clauses = sum(1 + len(generator.ifs) for generator in node.generators)
            if clauses >= 4:
                yield "dense-comprehension", node.lineno, f"This comprehension has {clauses} for and if clauses. Unfold it into loops, or name the steps.", {}
        elif isinstance(node, ast.IfExp) and isinstance(node.orelse, ast.IfExp) and isinstance(node.orelse.orelse, ast.IfExp):
            yield "dense-comprehension", node.lineno, "Three conditional expressions are chained here. An if statement or a lookup table reads more plainly.", {}


def _dropped_work(tree: ast.Module) -> Iterator[tuple]:
    """Work handed to an executor or a thread and then dropped: its failure goes unseen, and nothing waits for it at shutdown."""
    for node in ast.walk(tree):
        call = node.value if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) else None
        method = call.func if call is not None and isinstance(call.func, ast.Attribute) else None
        if method is not None and method.attr == "submit" and _POOL.search(_dotted(method.value)):
            yield ("dropped-task", node.lineno, "The future submit returns is dropped, so an exception in that work is never seen. Keep it and call result(), "
                   "or wait on all of them before moving on.", {})
        elif method is not None and method.attr == "start" and _called(method.value) in ("threading.Thread", "Thread") and not _is_daemon(method.value):
            yield ("dropped-task", node.lineno, "This thread is started and dropped, so this code can't stop it, and one that loops keeps the process from "
                   "exiting. Keep it and give it a way to stop, or hand the work to an executor that's shut down.", {})


def _is_daemon(call: ast.Call) -> bool:
    """daemon=True says on purpose that nothing will wait for this thread."""
    return any(keyword.arg == "daemon" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in call.keywords)


def _lazy_relations(tree: ast.Module, text: str) -> Iterator[tuple]:
    """Django loads a related object on first access, so reading one per row of a plain queryset is a query per row. Only relations this file
    declares count, since `o.created_at.year` reads the same way and needs no query."""
    relations = set(re.findall(r"^[ \t]*(\w+)[ \t]*=[ \t]*(?:models\.)?(?:ForeignKey|OneToOneField)\(", text, re.M))
    if not relations:
        return
    loops = [(node.target, node.iter, node.body) for node in ast.walk(tree) if isinstance(node, (ast.For, ast.AsyncFor))]
    loops += [(generator.target, generator.iter, [node.elt if hasattr(node, "elt") else node.value]) for node in ast.walk(tree)
              if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)) for generator in node.generators[:1]]
    for target, source, body in loops:
        if not (isinstance(target, ast.Name) and _QUERYSET.search(_source(source)) and not _PREFETCHED.search(_source(source))):
            continue
        called = {id(node.func) for statement in body for node in ast.walk(statement) if isinstance(node, ast.Call)}
        read = next((node for statement in body for node in ast.walk(statement) if isinstance(node, ast.Attribute) and id(node) not in called
                     and isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id == target.id
                     and node.value.attr in relations), None)
        if read is not None:
            yield ("query-in-loop", read.lineno, f"`{read.value.attr}` is a relation, so each row here runs another query to load it. Add "
                   f"select_related('{read.value.attr}') or prefetch_related to the queryset.", {})


def _source(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, RecursionError):
        return ""


def _index_loops(tree: ast.Module) -> Iterator[tuple]:
    """`for i in range(len(xs))` that only ever reads `xs[i]` is `for x in xs`, except `self` in __iter__, where that would recurse."""
    in_iter = {id(node) for function in ast.walk(tree) if isinstance(function, FUNCTIONS) and function.name == "__iter__" for node in ast.walk(function)}
    for loop in (node for node in ast.walk(tree) if isinstance(node, ast.For)):
        call = loop.iter
        if not (isinstance(loop.target, ast.Name) and _called(call) == "range" and len(call.args) == 1 and _called(call.args[0]) == "len"
                and len(call.args[0].args) == 1 and isinstance(call.args[0].args[0], ast.Name) and not (call.args[0].args[0].id == "self" and id(loop) in in_iter)):
            continue
        index, sequence = loop.target.id, call.args[0].args[0].id
        uses = [node for statement in loop.body for node in ast.walk(statement) if isinstance(node, ast.Name) and node.id == index]
        reads = [node for statement in loop.body for node in ast.walk(statement) if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                 and node.value.id == sequence and isinstance(node.slice, ast.Name) and node.slice.id == index and isinstance(node.ctx, ast.Load)]
        if uses and len(uses) == len(reads):
            yield "range-len-loop", loop.lineno, f"This loop only reads {sequence}[{index}]. `for item in {sequence}` says so directly.", {}


def findings(tree: ast.Module, path: str, is_test: bool, text: str = "") -> list[tuple]:
    """(rule, line, message, overrides) for one parsed module."""
    found = [*_lazy_after_close(tree), *_locks(tree), *_cache_reads_user(tree), *_clients_per_call(tree, is_test), *_io_in_property(tree),
             *_unbounded_queues(tree, is_test), *_nonatomic_writes(tree, text, is_test), *_dense_expressions(tree), *_index_loops(tree),
             *_lazy_relations(tree, text)]
    if is_test:  # tests submit and start work to probe it
        found += [*_not_assertions(tree), *_fixed_resources(tree), *_unseeded_random(tree, text), *([] if _INTEGRATION_FOLDER.search(path) else _network_calls(tree, text))]
    else:
        found += _dropped_work(tree)
    return found
