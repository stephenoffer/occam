"""JavaScript and TypeScript checks that need more than one pattern: Express routes and middleware, ORM writes, clients, test mocks and markup.

They report under the Python rules' ids where the failure is the same, so `rules` and the catalog describe one thing. fail-open blocks `gate`, as
the Python rule does. None is high severity with high confidence, so none sends an agent back at Stop.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Iterator

from .py_helpers import PUBLIC_ROUTE
from .source import Source

# `app.post("/x", requireUser, async (req, res) => ...)`: the receiver names a server or router, and the path is a string.
_ROUTE = re.compile(r"^[ \t]*(?:app|router|api|server|routes|\w+Router)\.(?:get|post|put|patch|delete)\(\s*(['\"`])", re.M)
_GUARD = re.compile(r"auth|login|session|jwt|token|verify|protect|guard|permission|role|admin|passport|require\w*user|ensure\w*|signed", re.I)
_GUARDS_ALL = re.compile(r"\.use\(\s*(?:['\"`][^'\"`]*['\"`]\s*,\s*)?[\w.]*(?:auth|jwt|session|passport|protect|guard|require\w*user|ensure\w*)", re.I)
_INLINE_HANDLER = re.compile(r"=>|\bfunction\b")
_CATCH = re.compile(r"\bcatch\s*(?:\([^)]{0,200}\))?\s*\{")
_MIDDLEWARE = re.compile(r"\(\s*\w+\s*(?::\s*\w+)?\s*,\s*\w+\s*(?::\s*\w+)?\s*,\s*next\s*(?::\s*\w+)?\s*\)")
_REFUSES = re.compile(r"\b(?:status|sendStatus)\(\s*40[13]\b|\bstatusCode\s*=\s*40[13]\b|\b(?:Unauthorized|Forbidden)\w*\(")
_RETURNS = r"(?:\s*:\s*[^{=;]{0,200})?"  # a TypeScript return type, as in `): Promise<void> {`
# Async function bodies: `async function f(...)`, `async (...) =>`, `async x =>`, and a class method `async f(...)`.
_ASYNC_BODY = re.compile(rf"\basync\s+(?:function\b[^{{(]*\([^)]{{0,500}}\){_RETURNS}|\([^)]{{0,500}}\){_RETURNS}\s*=>|\w+\s*=>|\w+\s*\([^)]{{0,500}}\){_RETURNS})\s*\{{")
# Request handlers: a function taking (req, res), or one named handler, as AWS Lambda's are.
_HANDLER_BODY = re.compile(rf"(?:\(\s*req\w*\s*(?::\s*\w+)?\s*,\s*res\w*\b[^)]{{0,200}}\){_RETURNS}\s*=>|\bfunction\s+\w*\s*\(\s*req\w*\s*(?::\s*\w+)?\s*,\s*res\w*\b[^)]{{0,200}}\){_RETURNS}|\bfunction\s+handler\s*\([^)]{{0,200}}\){_RETURNS}|\bhandler\s*=\s*async\s*\([^)]{{0,200}}\){_RETURNS}\s*=>)\s*\{{")
_WRITE = re.compile(r"\bawait\s+((?:this\.)?\w+)[\w$.]*\.(?:create|createMany|update|updateMany|upsert|delete|deleteMany|insert|insertMany|save|destroy|bulkCreate)\s*\(")
_TRANSACTION = re.compile(r"\$transaction|\btransaction\s*\(|\.transaction\b|\bBEGIN\b|startSession|withTransaction", re.I)
_FIND_MANY = re.compile(r"\.findMany\s*\(")
_PAGED = re.compile(r"\b(?:take|cursor|skip|first|last|limit)\b|\bin\s*:|\b\w*[iI]d\s*[:,}]")  # paged, or narrowed by an id
_CLIENT = re.compile(r"\bnew\s+(PrismaClient|Pool|MongoClient|Redis|IORedis|Sequelize)\s*\(")
_TEST_STEM = re.compile(r"^(.+?)\.(?:test|spec)\.[cm]?[jt]sx?$")
_MOCKED = re.compile(r"\b(?:jest|vi)\.(?:mock|doMock)\(\s*['\"](\.{1,2}/[^'\"]+)['\"]")
# One tag, attribute braces and all, since `onChange={(e) => f(e)}` holds a `>` that isn't the tag's end. Two levels of braces is enough for markup.
_TAG = r"(?:[^>{]|\{(?:[^{}]|\{[^{}]{0,2000}\}){0,2000}\}){0,4000}>"
_TAGS = {name: re.compile(rf"<{name}\b{_TAG}") for name in ("a", "button", "input", "select", "textarea", "div", "span", "li", "td", "img")}
_EMPTY_HANDLER = re.compile(r"\bon(?:Click|Submit|Change)=\{\s*(?:\(\s*\)\s*=>\s*(?:\{\s*\}|null|undefined)|undefined|null)\s*\}")
_TOGGLES = re.compile(r"\bon(?:Click|click)=|@click|v-on:|on:click|\bdata-(?:bs-)?toggle=")
_NAMED = re.compile(r"\b(?:aria-label|aria-labelledby|title)=")
_ICON_ONLY = re.compile(r"\s*<(?:svg|i|[A-Z]\w*Icon|Icon)\b[^>]{0,2000}?(?:/>|>\s*</(?:svg|i)>)\s*</button>")


def _closing(code: str, opening: int, pair: str) -> int:
    """The offset of the bracket closing the one at `opening`, or -1. Strings and comments are already blanked in `code`."""
    depth = 0
    for index in range(opening, len(code)):
        if code[index] == pair[0]:
            depth += 1
        elif code[index] == pair[1]:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _bodies(source: Source, head: re.Pattern) -> Iterator[tuple[int, int]]:
    for match in head.finditer(source.code):
        end = _closing(source.code, match.end() - 1, "{}")
        if end > 0:
            yield match.end(), end


def _top_level_arguments(code: str) -> list[str]:
    """Arguments split at commas outside brackets. Strings are blanked in `code`, so their commas are gone."""
    parts, depth, start = [], 0, 0
    for index, character in enumerate(code):
        depth += character in "([{"
        depth -= character in ")]}"
        if character == "," and depth == 0:
            parts.append(code[start:index])
            start = index + 1
    return [*parts, code[start:]]


def _routes(source: Source) -> Iterator[tuple]:
    """A route without the guard most of its siblings in this file use. A file-wide `.use(auth...)` guards them all."""
    if _GUARDS_ALL.search(source.code):
        return
    routes = []
    for match in _ROUTE.finditer(source.code):
        close = _closing(source.code, source.code.rfind("(", match.start(), match.end()), "()")
        path_end = source.text.find(match.group(1), match.end())
        path = source.text[match.end():path_end] if 0 < path_end < close else ""
        arguments = _top_level_arguments(source.code[path_end + 1:close])[1:] if path else []  # [0] is what's left of the path
        inline = next((index for index, argument in enumerate(arguments) if _INLINE_HANDLER.search(argument)), len(arguments) - 1)
        if path.startswith("/") and arguments:
            routes.append((source.line_of(match.start()), path, any(_GUARD.search(argument) for argument in arguments[:inline])))
    guarded = sum(guard for _, _, guard in routes)
    if len(routes) < 3 or guarded * 2 < len(routes):
        return
    for line, path, guard in routes:
        words = "_".join(re.findall(r"[a-z]+", path.lower()))
        if not guard and not PUBLIC_ROUTE.search(words):
            yield "missing-auth", line, f"{guarded} of {len(routes)} routes in this file take an auth middleware and {path} doesn't. Add it, or record why this one is public.", {}


def _fail_open(source: Source) -> Iterator[tuple]:
    """Middleware that refuses a bad request with 401 or 403, and calls next() from its catch, lets the request through when checking it threw.
    Middleware that never refuses, and only attaches a user when it can, does that on purpose."""
    for match in _CATCH.finditer(source.code):
        end = _closing(source.code, match.end() - 1, "{}")
        block = source.code[match.end():end] if end > 0 else ""
        allowed = re.search(r"\bnext\(\s*\)", block)
        before = source.code[max(0, match.start() - 3000):match.start()]
        heads = list(_MIDDLEWARE.finditer(before))
        middleware = before[heads[-1].start():] if heads else ""
        if allowed and middleware and _GUARD.search(middleware) and _REFUSES.search(middleware):
            yield ("fail-open", source.line_of(match.end() + allowed.start()), "This middleware refuses bad requests, but calls next() when checking one "
                   "throws, so an error lets the request through. Respond 401 or 403, or pass the error on with next(error).", {"confidence": "medium"})


def _writes_without_transaction(source: Source) -> Iterator[tuple]:
    """Two awaited writes through one client, as `prisma.a.update` then `prisma.b.update`. A database write and a cache delete aren't one store."""
    reported = set()
    for start, end in _bodies(source, _ASYNC_BODY):
        body = source.code[start:end]
        writes = list(_WRITE.finditer(body))
        second = next((later for index, earlier in enumerate(writes) for later in writes[index + 1:] if later.group(1) == earlier.group(1)), None)
        line = source.line_of(start + second.start()) if second else 0
        if line and not _TRANSACTION.search(body) and line not in reported:
            reported.add(line)
            yield ("multi-write-no-transaction", line, f"This function awaits {len(writes)} writes with no transaction, so a failure between them leaves the first "
                   "done and the rest not. Wrap them in one, such as prisma.$transaction, or say why half done is safe.", {})


def _in_handlers(source: Source) -> list[tuple[int, int]]:
    """Where request handling happens: inside a route's own call, whose handler may be a bare expression, and in a function taking (req, res)."""
    calls = [(match.start(), _closing(source.code, source.code.rfind("(", match.start(), match.end()), "()")) for match in _ROUTE.finditer(source.code)]
    return [*((start, end) for start, end in calls if end > 0), *_bodies(source, _HANDLER_BODY)]


def _unpaged(source: Source, handlers: list[tuple[int, int]]) -> Iterator[tuple]:
    for match in _FIND_MANY.finditer(source.code):
        end = _closing(source.code, match.end() - 1, "()")
        inside = any(start <= match.start() < stop for start, stop in handlers)
        if inside and end > 0 and not _PAGED.search(source.code[match.end():end]):
            yield "unpaginated-query", source.line_of(match.start()), "This handler returns findMany with no take, so it reads every row there is. Page it, and cap the page size.", {}


def _clients(source: Source, handlers: list[tuple[int, int]]) -> Iterator[tuple]:
    """A database client made in a request handler opens a new pool on every request. A factory or a script's main makes one on purpose."""
    for match in _CLIENT.finditer(source.code):
        if any(start <= match.start() < stop for start, stop in handlers):
            yield ("client-per-call", source.line_of(match.start()), f"new {match.group(1)}() in a request handler opens a fresh pool on every request and "
                   "leaks the last. Make one at module level and import it.", {})


def _mocks_subject(source: Source) -> Iterator[tuple]:
    """A test that mocks the module it's named for, resolved from where the test is: `cart.test.ts` beside `cart.ts`, or in `__tests__` below it."""
    stem = _TEST_STEM.match(posixpath.basename(source.path))
    if not stem:
        return
    folder = posixpath.dirname(source.path)
    subjects = {posixpath.join(folder, stem.group(1))}
    if posixpath.basename(folder) in ("__tests__", "tests", "test"):
        subjects.add(posixpath.join(posixpath.dirname(folder), stem.group(1)))
    for match in _MOCKED.finditer(source.text):
        mocked = posixpath.splitext(posixpath.normpath(posixpath.join(folder, match.group(1))))[0]
        if mocked in subjects or mocked.endswith("/index") and posixpath.dirname(mocked) in subjects:
            yield ("mock-of-subject", source.line_of(match.start()), f"This test mocks {match.group(1)}, the module it's named for, so it checks the mock and not "
                   "the code. Mock only what that module calls out to.", {})


def _inside_a_label(text: str, offset: int) -> bool:
    opened = text.rfind("<label", max(0, offset - 500), offset)
    return opened >= 0 and text.find("</label", opened, offset) < 0


def _markup(source: Source) -> Iterator[tuple]:
    text = source.text
    for match in _EMPTY_HANDLER.finditer(text):
        yield "dead-control", source.line_of(match.start()), "This control does nothing when used: its handler is empty.", {}
    for tag in _TAGS["a"].finditer(text):
        if re.search(r"\bhref=(['\"])#\1", tag.group(0)) and not _TOGGLES.search(tag.group(0)):
            yield "dead-control", source.line_of(tag.start()), "This link goes nowhere and has no handler, so using it does nothing.", {}
    for name in ("div", "span", "li", "td", "img"):
        for tag in _TAGS[name].finditer(text):
            found = tag.group(0)
            if "onClick=" in found and "role=" in found and not re.search(r"\btab[iI]ndex=|\bonKey\w*=", found):
                yield "a11y-missing", source.line_of(tag.start()), "This clickable element has a role but no tabIndex or key handler, so a keyboard can't reach or use it.", {}
    for tag in _TAGS["button"].finditer(text):
        if not _NAMED.search(tag.group(0)) and _ICON_ONLY.match(text, tag.end()):
            yield "a11y-missing", source.line_of(tag.start()), "This button shows only an icon and has no aria-label or title, so a screen reader announces nothing useful.", {}
    for name in ("input", "select", "textarea"):
        for tag in _TAGS[name].finditer(text):
            found = tag.group(0)
            if not (_NAMED.search(found) or re.search(r"\bid=|\btype=['\"](?:hidden|submit|button|reset|image)['\"]", found) or _inside_a_label(text, tag.start())):
                yield "a11y-missing", source.line_of(tag.start()), "This field has no label, aria-label or id for a label to point at, so assistive technology can't name it.", {}


def findings(source: Source, is_test: bool) -> Iterable[tuple]:
    """(rule, line, message, overrides) for one JavaScript or TypeScript file."""
    if is_test:
        return list(_mocks_subject(source))
    handlers = _in_handlers(source)
    return [*_routes(source), *_fail_open(source), *_writes_without_transaction(source), *_unpaged(source, handlers), *_clients(source, handlers), *_markup(source)]
