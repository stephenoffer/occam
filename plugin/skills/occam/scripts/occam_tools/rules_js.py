"""JavaScript and TypeScript checks that need more than one pattern: Express routes and middleware, ORM writes, clients, test mocks and markup.

They report under the Python rules' ids where the failure is the same, so `rules` and the catalog describe one thing. fail-open blocks `gate`, as
the Python rule does. None is high severity with high confidence, so none sends an agent back at Stop.
"""

from __future__ import annotations

import bisect
import posixpath
import re
from collections.abc import Iterable, Iterator

from . import js_syntax as js
from . import rules_js_requests, rules_js_secure, rules_js_state
from .py_helpers import PUBLIC_ROUTE
from .source import Source

# `app.post("/x", requireUser, async (req, res) => ...)`: the receiver names a server or router, and the path is a string.
_ROUTE = re.compile(r"^[ \t]*(?:app|router|api|server|routes|\w+Router)\.(?P<method>get|post|put|patch|delete)\(\s*(['\"`])", re.M)
_GUARD = re.compile(r"auth|login|session|jwt|token|verify|protect|guard|permission|role|admin|passport|require\w*user|ensure\w*|signed", re.I)
_GUARDS_ALL = re.compile(r"\.use\(\s*(?:['\"`][^'\"`]*['\"`]\s*,\s*)?[\w.]*(?:auth|jwt|session|passport|protect|guard|require\w*user|ensure\w*)", re.I)
_INLINE_HANDLER = re.compile(r"=>|\bfunction\b")
# What decides who may, once who is asking is known: a role, permission or policy check among a route's middleware.
_ROLE_GUARD = re.compile(r"role|admin|permission|authori[sz]e|polic|abilit|\bcan[A-Z_]\w*|scope|restrict|owner|rbac|\bacl\b|grant|allow", re.I)
_CHANGES = {"post", "put", "patch", "delete"}
_CATCH = re.compile(r"\bcatch\s*(?:\([^)]{0,200}\))?\s*\{")
_TYPE = r"(?::(?:[^,()<>]|<[^<>()]{0,120}>){1,120})?"  # `req: express.Request<{}, {}, Body>` too
_MIDDLEWARE = re.compile(rf"\(\s*\w+\s*{_TYPE},\s*\w+\s*{_TYPE},\s*next\s*{_TYPE}\)")
_REFUSES = re.compile(r"\b(?:status|sendStatus)\(\s*40[13]\b|\bstatusCode\s*=\s*40[13]\b|\b(?:Unauthorized|Forbidden)\w*\(")
_RETURNS = r"(?:\s*:\s*[^{=;]{0,200})?"  # a TypeScript return type, as in `): Promise<void> {`
# Async function bodies: `async function f(...)`, `async (...) =>`, `async x =>`, and a class method `async f(...)`.
_ASYNC_BODY = re.compile(rf"\basync\s+(?:function\b[^{{(]{{0,200}}\([^)]{{0,500}}\){_RETURNS}|\([^)]{{0,500}}\){_RETURNS}\s*=>|\w+\s*=>|\w+\s*\([^)]{{0,500}}\){_RETURNS})\s*\{{")
# Request handlers: a function taking (req, res), or one named handler, as AWS Lambda's are.
_HANDLER_BODY = re.compile(rf"(?:\(\s*req\w*\s*(?::\s*\w+)?\s*,\s*res\w*\b[^)]{{0,200}}\){_RETURNS}\s*=>|\bfunction\s+\w*\s*\(\s*req\w*\s*(?::\s*\w+)?\s*,\s*res\w*\b[^)]{{0,200}}\){_RETURNS}|\bfunction\s+handler\s*\([^)]{{0,200}}\){_RETURNS}|\bhandler\s*=\s*async\s*\([^)]{{0,200}}\){_RETURNS}\s*=>)\s*\{{")
_WRITE = re.compile(r"\bawait\s+((?:this\.)?\w+)[\w$.]*\.(?:create|createMany|update|updateMany|upsert|delete|deleteMany|insert|insertMany|save|destroy|bulkCreate)\s*\(")
# A database client's name, as the root of a write. A payment API's or a cache's update isn't a row in this database.
# A Sequelize or Mongoose model is a capitalized name, as `User.update`.
_DATABASE = re.compile(r"(?:this\.)?(?:prisma|db|database|tx|trx|knex|sequelize|em|entityManager|manager|queryRunner|models|\w*[rR]epo(?:sitory)?|[A-Z]\w*)")
_SEED_SCRIPT = re.compile(r"(?:^|/)(?:seeds?|migrations?|scripts?)(?:/|\.[cm]?[jt]s$)")
_STORIES = re.compile(r"\.stories\.[cm]?[jt]sx?$")
_EMPTY_LINK = re.compile(r"\bhref=(['\"])#\1")
_LABELLED = re.compile(r"\bid=|\btype=['\"](?:hidden|submit|button|reset|image)['\"]")
_TRANSACTION = re.compile(r"\$transaction|\btransaction\s*\(|\.transaction\b|\bBEGIN\b|startSession|withTransaction", re.I)
_FIND_MANY = re.compile(r"\.findMany\s*\(")
_PAGED = re.compile(r"\b(?:take|cursor|skip|first|last|limit)\b|\bin\s*:|\b\w*[iI]d\s*[:,}]")  # paged, or narrowed by an id
_CLIENT = re.compile(r"\bnew\s+(PrismaClient|Pool|MongoClient|Redis|IORedis|Sequelize)\s*\(")
_TEST_STEM = re.compile(r"^(.+?)\.(?:test|spec)\.[cm]?[jt]sx?$")
_MOCKED = re.compile(r"\b(?:jest|vi)\.(?:mock|doMock)\(\s*['\"](\.{1,2}/[^'\"]+)['\"]")
_TAG_START = re.compile(r"<(a|button|input|select|textarea|div|span|li|td|img)\b")
_TAG_STOP = re.compile(r"[{}>]")
MAX_TAG = 4000
MAX_BODY = 50_000  # a function body longer than this isn't read for writes, so nested bodies can't make that quadratic
MAX_CATCH = 5_000  # nor a catch block for next()
MAX_ARGUMENT = 500  # what's read of each route argument
_ARGUMENT_MARK = re.compile(r"[,(\[{]")
_EMPTY_HANDLER = re.compile(r"\bon(?:Click|Submit)=\{\s*(?:\(\s*\)\s*=>\s*(?:\{\s*\}|null|undefined)|undefined|null)\s*\}")
_TOGGLES = re.compile(r"\bon(?:Click|click)=|@click|v-on:|on:click|\bdata-(?:bs-)?toggle=")
_NAMED = re.compile(r"\b(?:aria-label|aria-labelledby|title)=")
_ICON_ONLY = re.compile(r"\s*<(?:svg|i|[A-Z]\w*Icon|Icon)\b[^>]{0,2000}?(?:/>|>\s*</(?:svg|i)>)\s*</button>")


def _pairs(code: str) -> dict[int, int]:
    return js.pairs(code)


def _bodies(source: Source, head: re.Pattern, pairs: dict[int, int]) -> Iterator[tuple[int, int]]:
    for match in head.finditer(source.code):
        end = pairs.get(match.end() - 1, -1)
        if end > 0:
            yield match.end(), end


def _tags(source: Source) -> Iterator[tuple[str, int, str]]:
    """(name, start, text) of each tag, in one pass. Braces hold attribute code, so the `>` in `onChange={(e) => f(e)}` doesn't end the tag. A tag in
    a string, such as HTML in a template, isn't markup, and one longer than MAX_TAG isn't either: reading resumes after it, never inside it."""
    text, position = source.text, 0
    while True:
        start = _TAG_START.search(text, position)
        if not start:
            return
        position = start.end()
        if source.code[start.start()] != "<":
            continue
        depth, cursor, limit, end = 0, start.end(), start.start() + MAX_TAG, -1
        while end < 0:
            stop = _TAG_STOP.search(text, cursor, limit)
            if not stop:
                break
            cursor = stop.end()
            if stop.group(0) == "{":
                depth += 1
            elif stop.group(0) == "}":
                depth = max(depth - 1, 0)
            elif depth == 0:
                end = cursor
        if end < 0:
            position = max(position, cursor)
            continue
        yield start.group(1), start.start(), text[start.start():end]
        position = end


def _top_level_arguments(code: str, start: int, end: int, pairs: dict[int, int]) -> list[str]:
    """Arguments between `start` and `end`, split at commas outside brackets. Each bracket jumps to its partner, so a route costs a few steps
    however much it holds, and each argument is read to MAX_ARGUMENT characters."""
    parts, cursor, position = [], start, start
    while True:
        mark = _ARGUMENT_MARK.search(code, position, end)
        if not mark:
            return [*parts, code[cursor:min(end, cursor + MAX_ARGUMENT)]]
        if mark.group(0) == ",":
            parts.append(code[cursor:min(mark.start(), cursor + MAX_ARGUMENT)])
            cursor = position = mark.end()
        else:
            closing = pairs.get(mark.start(), -1)
            if closing < 0 or closing >= end:
                return [*parts, code[cursor:min(end, cursor + MAX_ARGUMENT)]]
            position = closing + 1


def _route_calls(source: Source, pairs: dict[int, int]) -> Iterator[tuple[re.Match, int, int]]:
    """(match, its opening parenthesis, its closing one) for each route whose call closes."""
    for match in _ROUTE.finditer(source.code):
        opening = source.code.rfind("(", match.start(), match.end())
        close = pairs.get(opening, -1)
        if close > 0:
            yield match, opening, close


# Routes anyone signed in, or anyone at all, is meant to reach: signing in and out, recovering an account, health checks, webhooks, and the
# caller's own records under `me`.
_OPEN_WORDS = {"login", "logout", "signin", "signout", "signup", "register", "registration", "refresh", "forgot", "reset", "health", "healthz", "ping",
               "ready", "live", "webhook", "webhooks", "callback", "oauth", "public", "verify", "confirm", "me"}
_ROLE_WORDS = {"role", "roles", "admin", "admins", "permission", "permissions", "privilege", "privileges", "grant", "promote", "demote", "ban", "suspend"}


def _words(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", text)}


def _resource(path: str) -> tuple[str, ...]:
    """A route's static segments, so `/posts` and `/posts/:id` are one resource and `/:id/role` another."""
    return tuple(segment for segment in path.strip("/").split("/") if segment and not segment.startswith((":", "{", "[")))


def _verb(method: str) -> str:
    return "create" if method == "post" else "change"


def _unguarded_alike(routes: list[tuple]) -> Iterator[tuple]:
    """Of routes (line, path, guarded, method, name), the unguarded ones that change something where a guarded sibling does the same kind of
    change to the same resource, or whose path or name is about roles. Creating a post where only admins edit and delete them is normal."""
    guarded = {(_resource(path), _verb(method)) for _, path, guard, method, _ in routes if guard and method in _CHANGES}
    for route in routes:
        _, path, guard, method, name = route
        words = _words(path + " " + name)
        if guard or method not in _CHANGES or words & _OPEN_WORDS:
            continue
        if (_resource(path), _verb(method)) in guarded or words & _ROLE_WORDS:
            yield route


def _routes(source: Source, pairs: dict[int, int]) -> Iterator[tuple]:
    """A route without the guard most of its siblings in this file use. A file-wide `.use(auth...)` guards them all, and csrf protection isn't
    auth. Under a file-wide auth, role checks are compared instead, like with like: see _unguarded_alike."""
    authenticated = bool(_GUARDS_ALL.search(source.code))
    routes = []
    for match, _, close in _route_calls(source, pairs):
        path_end = source.text.find(match.group(2), match.end(), min(close, match.end() + 500))
        path = source.text[match.end():path_end] if path_end > 0 else ""
        arguments = _top_level_arguments(source.code, path_end + 1, close, pairs)[1:] if path else []  # [0] is what's left of the path
        inline = next((index for index, argument in enumerate(arguments) if _INLINE_HANDLER.search(argument)), len(arguments) - 1)
        guard_pattern = _ROLE_GUARD if authenticated else _GUARD
        guard = any(guard_pattern.search(argument) and not re.search(r"csrf", argument, re.I) for argument in arguments[:inline])
        if path.startswith("/") and arguments:
            routes.append((source.line_of(match.start()), path, guard, match.group("method"), ""))
    guarded = sum(route[2] for route in routes)
    if len(routes) < 3 or guarded * 2 < len(routes) or (authenticated and guarded < 2):
        return
    if authenticated:
        for line, path, _, _, _ in _unguarded_alike(routes):
            yield ("missing-auth", line, f"{guarded} of {len(routes)} routes in this file take a role or permission check, including one that makes "
                   f"the same kind of change, and {path} doesn't. Add it, or record why any signed-in user may do this.", {})
        return
    for line, path, guard, _, _ in routes:
        words = "_".join(re.findall(r"[a-z]+", path.lower()))
        if not guard and not PUBLIC_ROUTE.search(words):
            yield "missing-auth", line, f"{guarded} of {len(routes)} routes in this file take an auth middleware and {path} doesn't. Add it, or record why this one is public.", {}


_NEST_ROLE = re.compile(r"@(?:Roles|Permissions|RequirePermissions|RequireRoles|HasRoles?|CheckPolicies|Policies|Scopes|UseGuards|Auth|Authorize|Admin\w*|Owner\w*|Can)\s*\(")
_NEST_PUBLIC = re.compile(r"@(?:Public|AllowAnonymous|SkipAuth|IsPublic)\s*\(")
_CLASS_BODY = re.compile(r"\bclass\s+[\w$]+[^{]{0,300}\{")


def _nest_roles(source: Source, pairs: dict[int, int], bodies: list) -> Iterator[tuple]:
    """A NestJS controller where most handlers carry a role or guard decorator, and one that makes the same kind of change to the same route,
    or one about roles, doesn't. Decorators on the class guard every method alike, so they aren't credited to the first."""
    code, text = source.code, source.text
    controller = code.find("@Controller(")
    opening = _CLASS_BODY.search(code, controller) if controller >= 0 else None
    if not opening:
        return
    routes = list(js.NEST_ROUTE.finditer(code, opening.end()))
    starts = [route.start() for route in routes]
    handlers, previous = [], opening.end()
    for function in bodies:
        if function.start < previous or not function.name:
            continue  # a function inside a method, or before the class
        index = bisect.bisect_left(starts, function.start) - 1
        route = routes[index] if index >= 0 and starts[index] >= previous else None
        if route:
            close = pairs.get(route.end() - 1, -1)
            path = text[route.end():close].strip(" '\"`") if close > 0 else ""
            decorators = code[previous:function.start]
            guard = bool(_NEST_ROLE.search(decorators)) or bool(_NEST_PUBLIC.search(decorators))
            handlers.append((source.line_of(function.start), "/" + path, guard, route.group(1).lower(), function.name))
        previous = function.end
    guarded = sum(handler[2] for handler in handlers)
    if len(handlers) < 3 or guarded < 2 or guarded * 2 < len(handlers):
        return
    for line, _, _, _, name in _unguarded_alike(handlers):
        yield ("missing-auth", line, f"{guarded} of {len(handlers)} handlers in this controller take a role or guard decorator, including one that "
               f"makes the same kind of change, and {name} doesn't, so any authenticated user can call it. Add it, or record why it's open to everyone.", {})


def _fail_open(source: Source, pairs: dict[int, int]) -> Iterator[tuple]:
    """Middleware that refuses a bad request with 401 or 403, and calls next() from a catch that refuses nothing itself, lets the request through when
    checking it threw. Middleware that never refuses, and only attaches a user when it can, does that on purpose, and a catch that refreshes an
    expired token and otherwise answers 401 is careful, not open."""
    for match in _CATCH.finditer(source.code):
        end = pairs.get(match.end() - 1, -1)
        block = source.code[match.end():min(end, match.end() + MAX_CATCH)] if end > 0 else ""
        allowed = re.search(r"\bnext\(\s*\)", block)
        before = source.code[max(0, match.start() - 3000):match.start()]
        heads = list(_MIDDLEWARE.finditer(before))
        middleware = before[heads[-1].start():] if heads else ""
        if allowed and middleware and _GUARD.search(middleware) and _REFUSES.search(middleware) and not _REFUSES.search(block):
            yield ("fail-open", source.line_of(match.end() + allowed.start()), "This middleware refuses bad requests, but calls next() when checking one "
                   "throws, so an error lets the request through. Respond 401 or 403, or pass the error on with next(error).", {"confidence": "medium"})


def _writes_without_transaction(source: Source, pairs: dict[int, int]) -> Iterator[tuple]:
    """Two awaited writes through one database client, as `prisma.a.update` then `prisma.b.update`. A payment API's or a cache's calls aren't one
    store's, and a seed script's main writes on purpose."""
    if _SEED_SCRIPT.search(source.path):
        return
    reported = set()
    for start, end in _bodies(source, _ASYNC_BODY, pairs):
        if end - start > MAX_BODY:
            continue
        body = source.code[start:end]
        writes = [write for write in _WRITE.finditer(body) if _DATABASE.fullmatch(write.group(1))]
        second = _second_write_to_one_store(writes)
        line = source.line_of(start + second.start()) if second else 0
        if line and not _in_a_transaction(source.code, start, end) and line not in reported:
            reported.add(line)
            yield ("multi-write-no-transaction", line, f"This function awaits {len(writes)} database writes with no transaction, so a failure between them "
                   "leaves the first done and the rest not. Wrap them in one, such as prisma.$transaction, or say why half done is safe.", {})


def _second_write_to_one_store(writes: list[re.Match]) -> re.Match | None:
    seen: set[str] = set()
    for write in writes:
        if write.group(1) in seen:
            return write
        seen.add(write.group(1))
    return None


def _in_a_transaction(code: str, start: int, end: int) -> bool:
    """The body opens one, or is itself the callback a transaction runs."""
    return bool(_TRANSACTION.search(code, start, end) or _TRANSACTION.search(code[max(0, start - 200):start]))


def _in_handlers(source: Source, pairs: dict[int, int]) -> list[tuple[int, int]]:
    """Where request handling happens, as disjoint spans: inside a route's own call, whose handler may be a bare expression, and in a function
    taking (req, res)."""
    spans = sorted([*((opening, close) for _, opening, close in _route_calls(source, pairs)), *_bodies(source, _HANDLER_BODY, pairs)])
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _inside(spans: list[tuple[int, int]], offset: int) -> bool:
    at = bisect.bisect_right(spans, (offset, float("inf"))) - 1
    return at >= 0 and spans[at][0] <= offset < spans[at][1]


def _unpaged(source: Source, pairs: dict[int, int], handlers: list[tuple[int, int]]) -> Iterator[tuple]:
    for match in _FIND_MANY.finditer(source.code):
        end = pairs.get(match.end() - 1, -1)
        if end > 0 and _inside(handlers, match.start()) and not _PAGED.search(source.code[match.end():min(end, match.end() + 5000)]):
            yield "unpaginated-query", source.line_of(match.start()), "This handler returns findMany with no take, so it reads every row there is. Page it, and cap the page size.", {}


def _clients(source: Source, handlers: list[tuple[int, int]]) -> Iterator[tuple]:
    """A database client made in a request handler opens a new pool on every request. A factory or a script's main makes one on purpose."""
    for match in _CLIENT.finditer(source.code):
        if _inside(handlers, match.start()):
            yield ("client-per-call", source.line_of(match.start()), f"new {match.group(1)}() in a request handler opens a fresh pool on every request and "
                   "leaks the last. Make one at module level and import it.", {})


def _mocks_subject(source: Source) -> Iterator[tuple]:
    """A test that mocks the module it's named for, resolved from where the test is: `cart.test.ts` beside `cart.ts`, or in `__tests__` below it. A
    partial mock that keeps the real module, through requireActual, tests the real code."""
    stem = _TEST_STEM.match(posixpath.basename(source.path))
    if not stem:
        return
    folder = posixpath.dirname(source.path)
    subjects = {posixpath.join(folder, stem.group(1))}
    if posixpath.basename(folder) in ("__tests__", "tests", "test"):
        subjects.add(posixpath.join(posixpath.dirname(folder), stem.group(1)))
    pairs = _pairs(source.code)
    for match in _MOCKED.finditer(source.text):
        mocked = posixpath.splitext(posixpath.normpath(posixpath.join(folder, match.group(1))))[0]
        opening = source.text.find("(", match.start())
        call = source.text[opening:pairs.get(opening, opening)]  # this mock's own arguments, not a neighbor's
        partial = re.search(r"\b(?:requireActual|importActual)\b", call)
        if (mocked in subjects or mocked.endswith("/index") and posixpath.dirname(mocked) in subjects) and not partial:
            yield ("mock-of-subject", source.line_of(match.start()), f"This test mocks {match.group(1)}, the module it's named for, so it checks the mock and not "
                   "the code. Mock only what that module calls out to.", {})


def _inside_a_label(text: str, offset: int) -> bool:
    opened = text.rfind("<label", max(0, offset - 500), offset)
    return opened >= 0 and text.find("</label", opened, offset) < 0


def _markup(source: Source) -> Iterator[tuple]:
    """Stories render controls on purpose, and an empty onChange beside `value` is React's read-only field."""
    if _STORIES.search(source.path):
        return
    for match in _EMPTY_HANDLER.finditer(source.text):
        if source.code[match.start()] == source.text[match.start()]:  # not inside a string
            yield "dead-control", source.line_of(match.start()), "This control does nothing when used: its handler is empty.", {}
    for name, start, found in _tags(source):
        line = source.line_of(start)
        if name == "a" and _EMPTY_LINK.search(found) and not _TOGGLES.search(found):
            yield "dead-control", line, "This link goes nowhere and has no handler, so using it does nothing.", {}
        elif name in ("div", "span", "li", "td", "img") and "onClick=" in found and "role=" in found and not re.search(r"\btab[iI]ndex=|\bonKey\w*=", found):
            yield "a11y-missing", line, "This clickable element has a role but no tabIndex or key handler, so a keyboard can't reach or use it.", {}
        elif name == "button" and not _NAMED.search(found) and _ICON_ONLY.match(source.text, start + len(found)):
            yield "a11y-missing", line, "This button shows only an icon and has no aria-label or title, so a screen reader announces nothing useful.", {}
        elif name in ("input", "select", "textarea") and not (_NAMED.search(found) or _LABELLED.search(found) or _inside_a_label(source.text, start)):
            yield "a11y-missing", line, "This field has no label, aria-label or id for a label to point at, so assistive technology can't name it.", {}


def _guarded(produce) -> list:
    try:
        return list(produce())
    except (RecursionError, ValueError, AttributeError, TypeError, IndexError, KeyError):  # occam: ignore[swallowed-exception] a module that breaks on odd code loses only its own findings
        return []


def findings(source: Source, is_test: bool) -> Iterable[tuple]:
    """(rule, line, message, overrides) for one JavaScript or TypeScript file. Each newer module runs guarded, so one that breaks on odd code
    loses only its own findings."""
    if is_test:
        return list(_mocks_subject(source))
    pairs = _pairs(source.code)
    handlers = _in_handlers(source, pairs)
    routes = [(opening, close) for _, opening, close in _route_calls(source, pairs)]
    bodies = _guarded(lambda: js.functions(source.code, pairs))
    return [*_routes(source, pairs), *_fail_open(source, pairs), *_writes_without_transaction(source, pairs), *_unpaged(source, pairs, handlers),
            *_clients(source, handlers), *_markup(source), *_guarded(lambda: _nest_roles(source, pairs, bodies)),
            *_guarded(lambda: rules_js_requests.findings(source, pairs, routes, bodies)), *_guarded(lambda: rules_js_secure.findings(source, pairs, bodies)),
            *_guarded(lambda: rules_js_state.findings(source, pairs, bodies, handlers))]
