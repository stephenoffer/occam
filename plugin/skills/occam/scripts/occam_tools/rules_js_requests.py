"""Where a request's values go in JavaScript and TypeScript: into an outbound fetch, a file path, HTML, a shell command, an ownership check,
a record changed by id, or a cache key. Express, Koa, Fastify, Next.js route handlers and NestJS each hand a request over differently.

A value is followed from where it's read (`req.query.url`, `await request.json()`, `searchParams.get('src')`, `@Param('id') id`) through
`const` and `let` declarations in the same block, which is how JavaScript scopes them. Converting it to a number or boolean, or escaping it,
ends the trail for the sinks that only care about text.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from typing import NamedTuple

from . import js_syntax as js
from .source import Source

# `request` is also an outgoing fetch Request, whose headers and url are the caller's own, so only a server request's body, query and
# params count under that name.
_SOURCE = re.compile(
    r"\b(?:req|ctx\.request|ctx)\s*\.\s*(?P<part>body|query|params|cookies|headers|files?)\b|\brequest\s*\.\s*(?P<server>body|query|params)\b"
    r"|\breq\s*\.\s*(?P<header>get|header)\s*\("
    r"|\b(?:req|request)\s*\.\s*(?P<payload>json|text|formData)\s*\(\s*\)"
    r"|\b(?P<search>searchParams)\s*\.\s*get(?:All)?\s*\("
    r"|\bevent\s*\.\s*(?P<lambda>body|queryStringParameters|pathParameters|multiValueQueryStringParameters)\b"
)
_PART = {"body": "body", "files": "body", "file": "body", "query": "query", "params": "params", "cookies": "header", "headers": "header",
         "queryStringParameters": "query", "multiValueQueryStringParameters": "query", "pathParameters": "params"}
# Next.js hands a route's parameters and a page's query to the function as `{ params }` and `{ searchParams }`.
_NEXT_FILE = re.compile(r"(?:^|/)(?:app/(?:.+/)?(?:route|page)|pages/api/.+)\.[cm]?[jt]sx?$")
_NEXT_ARGUMENT = re.compile(r"[({,]\s*\{\s*(?:params|searchParams)\b[^{}]{0,200}\}\s*[:)]")
_NEXT_SOURCE = re.compile(r"(?<![\w$.])(?P<next>params|searchParams)\b(?!\s*:)")
_NEST_PARAMETER = re.compile(r"@(?P<decorator>Body|Query|Param|Headers|Req|Request|UploadedFile)\s*\([^()]{0,200}(?:\([^()]{0,100}\)[^()]{0,100})?\)\s*(?:(?:private|public|readonly)\s+)*([A-Za-z_$][\w$]*)")
_NEST_PART = {"Body": "body", "Query": "query", "Param": "params", "Headers": "header", "Req": "body", "Request": "body", "UploadedFile": "body"}
_DECLARATION = re.compile(r"\b(?:const|let|var)\s+(?:([A-Za-z_$][\w$]*)|(\{[^{}]{0,400}\}|\[[^\[\]]{0,200}\]))\s*(?::[^=;\n]{1,200}?)?=(?![=>])")
_IDENTIFIER = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*(?![\w$])")
_NAME = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*(?![\w$])(?!\s*\()")  # a value's name, not a function called
_FUNCTION_VALUE = re.compile(r"\s*(?:async\s+)?(?:function\b|class\b|\([^()]{0,300}\)\s*(?::[^=;{}]{0,100})?=>|[\w$]+\s*=>)")
# What leaves no text of the request: a number, a boolean, an escaped or encoded string, a file's last segment.
_NEUTRAL = re.compile(r"\s*(?:await\s+)?(?:[!+]|typeof\b|(?:Number|parseInt|parseFloat|BigInt|Boolean|Math\.\w+|encodeURIComponent|encodeURI|\w*[eE]scape\w*|"
                      r"sanitize\w*|\w*[pP]urify\w*\.sanitize|(?:path\.)?basename|validator\.\w+|Date\.parse|new\s+Date|isNaN|Number\.\w+)\s*\()")
_COMPARES = re.compile(r"[!=]==?|[<>]=?(?!=)|\binstanceof\b|\.(?:test|has|includes|startsWith|endsWith)\s*\(")
_TERNARY = re.compile(r"\?(?![.?])")
# Reading a record, not taking a value from the request: `await prisma.doc.findUnique({ where: { id: req.params.id } })`.
_LOADS = re.compile(r"\.(?:find\w*|query\w*|load\w*|fetch\w*|select\w*|first|exec|count|aggregate|retrieve\w*)\s*\(|\bawait\s+(?!\(?\s*(?:req|request|ctx|context|params|searchParams)\b)")
_CHAIN = r"[A-Za-z_$][\w$]*(?:\s*\??\.\s*[\w$]+|\[[^\[\]\n]{0,60}\])*"
_LEAD = re.compile(rf"\s*(?:await\s+)?(?:new\s+URL\s*\(|String\s*\(|encodeURI\s*\()?\s*({_CHAIN})")
_PURE_CHAIN = re.compile(rf"\s*({_CHAIN})\s*")


class _Binding(NamedTuple):
    offset: int
    end: int             # the end of the block it's declared in
    parts: frozenset     # body, query, params or header
    text: bool           # still the text the client sent: not loaded by it, converted to a number, or escaped
    direct: bool         # taken from the request, perhaps converted, but not loaded from storage by it


class Requests:
    """Request values in one file, and every name that holds one."""

    def __init__(self, source: Source, brackets: dict[int, int], bodies: list[js.Function]):
        self.source = source
        self.brackets = brackets
        self.view = js.with_interpolations(source)
        self.next = bool(_NEXT_FILE.search(source.path) or _NEXT_ARGUMENT.search(source.code))
        # name -> (offsets, bindings, parents): kept in offset order, each with the earlier binding of the name whose block holds it, so a lookup
        # climbs enclosing blocks instead of walking every earlier sibling.
        self.bindings: dict[str, tuple[list[int], list[_Binding], list[int]]] = {}
        code = source.code
        declarations = list(_DECLARATION.finditer(code))
        scopes = js.innermost(js.blocks(code, brackets), [match.start() for match in declarations])
        starts = [function.start for function in bodies]
        events = [(match.start(), 0, match) for match in _NEST_PARAMETER.finditer(code)] + [(match.start(), 1, match) for match in declarations]
        for _, kind, match in sorted(events, key=lambda event: (event[0], event[1])):
            if kind == 0:
                index = bisect.bisect_right(starts, match.start())
                if index < len(bodies):
                    self._bind([match.group(2)], _Binding(match.start(), bodies[index].end, frozenset([_NEST_PART[match.group("decorator")]]), True, True))
                continue
            if _FUNCTION_VALUE.match(code, match.end()):
                continue  # a function's body isn't its value
            end = js.statement_end(code, match.end(), brackets)
            parts, text, direct = self.read(self.view[match.end():end], match.start())
            if parts:
                loads = bool(_LOADS.search(code, match.end(), end))
                scope = scopes.get(match.start(), (0, len(code)))
                self._bind(_declared_names(match), _Binding(match.start(), scope[1], frozenset(parts), text and not loads, direct and not loads))

    def _bind(self, names: list[str], binding: _Binding) -> None:
        for name in names:
            offsets, items, parents = self.bindings.setdefault(name, ([], [], []))
            parent = len(items) - 1
            while parent >= 0 and items[parent].end <= binding.offset:
                parent = parents[parent]
            offsets.append(binding.offset)
            items.append(binding)
            parents.append(parent)

    def binding(self, name: str, offset: int) -> _Binding | None:
        """The binding of `name` whose block holds `offset`: the last one declared before it, or the nearest enclosing one."""
        entry = self.bindings.get(name)
        if not entry:
            return None
        offsets, items, parents = entry
        index = bisect.bisect_left(offsets, offset) - 1
        while index >= 0 and items[index].end <= offset:
            index = parents[index]
        return items[index] if index >= 0 else None

    def read(self, expression: str, offset: int) -> tuple[set, bool, bool]:
        """(parts of the request in this expression, whether one is still the client's text, whether one is taken straight from the request)."""
        parts: set[str] = set()
        text = direct = False
        for match in _SOURCE.finditer(expression):
            parts.add(_part_of(match))
            text = direct = True
        if self.next:
            for match in _NEXT_SOURCE.finditer(expression):
                parts.add("params" if match.group("next") == "params" else "query")
                text = direct = True
        for match in _NAME.finditer(expression):
            found = self.binding(match.group(0), offset)
            if found:
                parts |= found.parts
                text = text or found.text
                direct = direct or found.direct
        if parts and (_NEUTRAL.match(expression) or (_COMPARES.search(expression) and not _TERNARY.search(expression))):
            text = False
        return parts, text, direct

    def text_at(self, start: int, end: int) -> bool:
        """The expression here holds text the client sent, as sent."""
        return self.read(self.view[start:end], start)[1]

    def lead_is_text(self, start: int, end: int, depth: int = 2) -> bool:
        """The expression's first operand is the client's text: what decides a URL's host, or where a path starts. A name declared as a
        template or concatenation here is read through, so `${API}/repos/${owner}` held in `url` isn't the client's URL."""
        expression = self.view[start:end]
        if expression.lstrip().startswith("`"):
            opening = start + expression.index("`")
            if self.source.text.startswith("${", opening + 1):
                inner = js.interpolations(self.source.text, opening + 1, min(end, len(self.source.text)))
                return bool(inner) and self.text_at(*inner[0])
            return False
        lead = _LEAD.match(expression)
        if not lead:
            return False
        if depth and re.fullmatch(r"[A-Za-z_$][\w$]*", lead.group(1)):
            declared = self.declared_value(lead.group(1), start)
            if declared and (self.source.code[declared[0]:declared[1]].lstrip().startswith("`") or "+" in self.source.code[declared[0]:declared[1]]):
                return self.lead_is_text(*declared, depth - 1)
        return self.text_at(start + lead.start(1), start + lead.end(1))

    def declared_value(self, name: str, before: int, reach: int = 5000) -> tuple[int, int] | None:
        """Where the last `const name = ...` within `reach` before `before` puts its value."""
        window = max(0, before - reach)
        declared = None
        for declared in re.finditer(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*(?::[^=;\n]{{1,100}})?=(?![=>])\s*", self.source.code[window:before]):
            pass
        if not declared:
            return None
        start = window + declared.end()
        return start, js.statement_end(self.source.code, start, self.brackets)


def _part_of(match: re.Match) -> str:
    if match.group("part") or match.group("server"):
        return _PART[match.group("part") or match.group("server")]
    if match.group("header"):
        return "header"
    if match.group("payload"):
        return "body"
    if match.group("search"):
        return "query"
    return _PART.get(match.group("lambda"), "body")


def _declared_names(match: re.Match) -> list[str]:
    if match.group(1):
        return [match.group(1)]
    names = []
    for part in match.group(2)[1:-1].split(","):
        part = part.strip()
        if part.startswith("..."):
            part = part[3:]
        part = part.split(":", 1)[-1].split("=", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", part):
            names.append(part)
    return names


class Context(NamedTuple):
    source: Source
    brackets: dict
    bodies: list          # every function body, in order
    named: dict           # function name -> its bodies
    requests: Requests


def context(source: Source, brackets: dict[int, int], bodies: list[js.Function]) -> Context:
    named: dict[str, list[js.Function]] = {}
    for function in bodies:
        if function.name:
            named.setdefault(function.name, []).append(function)
    return Context(source, brackets, bodies, named, Requests(source, brackets, bodies))


def _befores(ctx: Context, offsets: list[int]) -> dict[int, str]:
    """For each offset, the code of the innermost function holding it, up to it, in one sweep. At module level, the 3000 characters before."""
    enclosing = js.enclosing_function(ctx.bodies, offsets)
    return {offset: ctx.source.code[enclosing[offset].start if offset in enclosing else max(0, offset - 3000):offset] for offset in offsets}


# ---------------------------------------------------------------- server-side request forgery

_FETCH = re.compile(r"(?<![\w$.])(?:fetch|got|ky|needle|axios|superagent|undici\.(?:request|fetch)|https?\.(?:get|request))\s*"
                    r"(?:\.\s*(?:get|post|put|patch|delete|head|request|stream)\s*)?(?:<[^()<>]{0,100}>\s*)?\(")
_URL_OPTION = re.compile(r"\b(?:url|baseURL|host|hostname)\b\s*(?P<colon>:)?\s*")
# A destination checked against something: the host or origin compared, an allow-list, or a resolved address.
_DESTINATION_CHECK = re.compile(r"\.\s*(?:hostname|host|origin)\b|(?i:allow\w*|whitelist|safe_?url|is_?private|private_?ip|internal_?ip|ssrf|blocklist|denylist|"
                                r"validate\w*url|assert\w*url)|\bdns\b|\blookup\s*\(|ipaddr|\bisIP\w*\s*\(")


def ssrf(ctx: Context) -> Iterator[tuple]:
    """A server fetching a URL whose start, so its scheme and host, is what the client sent. A value placed after a fixed base, such as an
    encoded path segment, can't change where the request goes."""
    code = ctx.source.code
    candidates = []
    for match in _FETCH.finditer(code):
        spans = js.argument_spans(code, match.end() - 1, ctx.brackets, 1)
        if not spans:
            continue
        start, end = spans[0]
        if code[start:end].lstrip().startswith("{"):
            option = _URL_OPTION.search(code, start, end)
            if not option:
                continue
            start = option.end() if option.group("colon") else option.start()
        if ctx.requests.lead_is_text(start, end):
            candidates.append(match.start())
    befores = _befores(ctx, candidates)
    for offset in candidates:
        if not _DESTINATION_CHECK.search(befores[offset]):
            yield ("ssrf", ctx.source.line_of(offset), "This fetches a URL the client chose, scheme and host included, so a caller can reach internal "
                   "services or cloud metadata through this server. Allow-list hosts, and check redirects and resolved addresses.", {})


# ---------------------------------------------------------------- paths

_FILE_SINK = re.compile(r"\b(?:res|reply|response)\s*\.\s*(?:sendFile|download)\s*\(|(?<![\w$])(?:fs|fsp|fsPromises|fse|promises)\s*\.\s*"
                        r"(?:readFile|readFileSync|createReadStream|createWriteStream|writeFile|writeFileSync|appendFile|appendFileSync|unlink|unlinkSync|"
                        r"rm|rmSync|readdir|readdirSync|copyFile|rename|renameSync)\s*\(|(?<![\w$.])(?:readFile|readFileSync|createReadStream|"
                        r"createWriteStream|writeFile|writeFileSync|unlink|readdir|rm)\s*\(")
_CONTAINED = re.compile(r"\.\s*startsWith\s*\(|\brelative\s*\(|realpath|[iI]nside|[sS]ub(?:[dD]ir|[pP]ath)|\bcontains\w*\s*\(")
_DOT_DOT = re.compile(r"""['"`]\.\.[/\\'"`]""")
_ROOT_OPTION = re.compile(r"\broot\s*:")


def path_traversal(ctx: Context) -> Iterator[tuple]:
    """A file read, written or sent at a path built from what the client sent, with no check that it stays under the folder meant. Express's
    sendFile with a `root` option refuses `..` itself."""
    code, text = ctx.source.code, ctx.source.text
    candidates = []
    for match in _FILE_SINK.finditer(code):
        spans = js.argument_spans(code, match.end() - 1, ctx.brackets, 3)
        if spans and ctx.requests.text_at(*spans[0]) and not any(_ROOT_OPTION.search(code, start, end) for start, end in spans[1:]):
            candidates.append((match.start(), spans[0]))
    befores = _befores(ctx, [offset for offset, _ in candidates])
    for offset, (start, end) in candidates:
        before = befores[offset]
        names = {name.group(0) for name in _NAME.finditer(ctx.requests.view[start:end])}
        checked = _CONTAINED.search(before) or _DOT_DOT.search(text, offset - len(before), offset) or any(
            re.search(rf"\.\s*(?:test|match)\s*\(\s*{re.escape(name)}\b|\b{re.escape(name)}\s*\.\s*(?:match|includes)\s*\(", before) for name in names)
        if not checked:
            yield ("path-traversal", ctx.source.line_of(offset), "This file path is built from what the client sent, and nothing checks it stays under "
                   "the folder meant, so `../` reaches any file the process can. Resolve it and check it starts with the root, or use sendFile's root "
                   "option.", {})


# ---------------------------------------------------------------- HTML

_TAG = re.compile(r"<[A-Za-z!/][\w-]*")
_RESPONDS = re.compile(r"\b(?:res|reply|response)\s*\.\s*(?:send|write|end)\s*\(|\bctx\s*\.\s*body\s*=")
_SANITIZER = re.compile(r"\b(?:DOMPurify|dompurify|purify|DomPurify)\s*\.\s*sanitize\s*\(|\bsanitize(?:Html|HTML)?\s*\(|\bfilterXSS\s*\(|\bxss\s*\(|"
                        r"\b\w*[eE]scape(?:Html|HTML)\w*\s*\(")
_MARKUP_SINK = re.compile(r"\.(?:innerHTML|outerHTML)\s*=(?!=)(?!\s*(?:\"[^\"\n]*\"|'[^'\n]*')\s*(?:;|$))|dangerouslySetInnerHTML|\bdocument\.write\(|\bv-html=|\{@html\b",
                          re.M)
_HTML_VALUE = re.compile(r"__html\s*:\s*|\.(?:innerHTML|outerHTML)\s*=\s*|document\.write\(\s*")


def server_html(ctx: Context) -> Iterator[tuple]:
    """HTML built on the server with a request value spliced in as is, so a link carrying markup runs script in whoever opens it."""
    code, text = ctx.source.code, ctx.source.text
    position, reported = 0, set()
    while True:
        opening = code.find("`", position)
        closing = code.find("`", opening + 1) if opening >= 0 else -1
        if closing < 0:
            break
        position = closing + 1
        if not _TAG.search(text, opening, closing):
            continue
        for start, end in js.interpolations(text, opening + 1, closing):
            line = ctx.source.line_of(start)
            if line not in reported and _PURE_CHAIN.fullmatch(text, start, end) and ctx.requests.text_at(start, end):
                reported.add(line)
                yield ("xss-sink", line, "Request text goes into this HTML unescaped, so markup in a link runs as script for whoever opens it. Escape it "
                       "for HTML, or render it through a template engine that does.", {})
    for match in _RESPONDS.finditer(code):
        if code[match.end() - 1] == "(":
            spans = js.argument_spans(code, match.end() - 1, ctx.brackets, 1)
        else:
            spans = [(match.end(), js.statement_end(code, match.end(), ctx.brackets))]
        line = ctx.source.line_of(match.start())
        if not spans or line in reported or "+" not in code[spans[0][0]:spans[0][1]] or not _TAG.search(text, *spans[0]):
            continue
        offset = spans[0][0]
        for operand in ctx.requests.view[spans[0][0]:spans[0][1]].split("+"):
            if _PURE_CHAIN.fullmatch(operand) and ctx.requests.text_at(offset, offset + len(operand)):
                reported.add(line)
                yield ("xss-sink", line, "Request text is concatenated into this HTML response unescaped. Escape it for HTML.", {})
                break
            offset += len(operand) + 1


def markup_sinks(ctx: Context) -> Iterator[tuple]:
    """Raw HTML sinks in the browser. One whose value went through a sanitizer, such as DOMPurify.sanitize, directly, by way of the `const`
    it names, or in a function of this file that builds it, is the safe form."""
    code = ctx.source.code
    for match in _MARKUP_SINK.finditer(code):
        value = _HTML_VALUE.search(code, match.start(), match.start() + 300)
        if value and _sanitized(ctx, value.end(), 2):
            continue
        yield "xss-sink", ctx.source.line_of(match.start()), None, {}


def _sanitized(ctx: Context, start: int, depth: int) -> bool:
    end = min(js.statement_end(ctx.source.code, start, ctx.brackets), start + 400)
    expression = ctx.requests.view[start:end]
    if _SANITIZER.search(expression):
        return True
    if depth == 0:
        return False
    for name in list(_IDENTIFIER.finditer(expression))[:20]:
        word = name.group(0)
        if expression[name.end():name.end() + 3].lstrip().startswith("("):
            if any(_SANITIZER.search(ctx.requests.view, function.start, function.end) for function in ctx.named.get(word, ())[:3]):
                return True
        else:
            declared = ctx.requests.declared_value(word, start, 4000)
            if declared and _sanitized(ctx, declared[0], depth - 1):
                return True
    return False


# ---------------------------------------------------------------- shell

_CHILD_PROCESS = re.compile(r"""(?:require\s*\(\s*|from\s+)['"](?:node:)?child_process['"]""")
_IMPORTS_EXEC = re.compile(r"\{[^{}]{0,300}\bexec(?:Sync)?\b[^{}]{0,300}\}\s*=\s*require\b|\bimport\s*\{[^{}]{0,300}\bexec(?:Sync)?\b")
_RUNNER_MEMBER = r"(?:child_process|childProcess|cp)\s*\.\s*(?:exec|execSync)"
_PROMISIFIED = re.compile(rf"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:util\s*\.\s*)?promisify\s*\(\s*(?:{_RUNNER_MEMBER}|(exec|execSync))\s*\)")
_SHELL_OPTION = re.compile(r"\bshell\s*:\s*(?:true|['\"`])")
_SPAWN = re.compile(r"(?<![\w$.])(?:spawn|spawnSync|execFile|execFileSync|(?:child_process|childProcess|cp)\s*\.\s*(?:spawn|spawnSync|execFile|execFileSync))\s*\(")
_CONCISE_ARROW = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?\(([^()]{0,200})\)\s*(?::[^=;{}()]{0,100})?=>(?!\s*\{)")
_DEFINITION_TAIL = re.compile(r"\s*(?::[^{};=()]{1,200})?\s*\{")


def shell(ctx: Context) -> Iterator[tuple]:
    """A command line built from runtime values and run through a shell by way of a helper: a promisified exec, a function that hands its first
    argument to exec, or spawn with `shell: true`. A direct `exec(`...${x}`)` is the text rule's."""
    code = ctx.source.code
    if not _CHILD_PROCESS.search(ctx.source.text):
        return
    runners = {"exec", "execSync"} if _IMPORTS_EXEC.search(code) else set()
    wrappers = {match.group(1) for match in _PROMISIFIED.finditer(code) if not match.group(2) or match.group(2) in runners}
    for _ in range(2):  # a helper of a helper
        names = sorted(runners | wrappers)
        if not names:
            break
        calls = list(re.finditer(rf"(?<![\w$.])(?:{'|'.join(map(re.escape, names))}|{_RUNNER_MEMBER})\s*\(\s*([A-Za-z_$][\w$]*)\s*[,)]", code))
        offsets = [call.start() for call in calls]
        # Helpers with a block body, and arrows whose body is one expression, `const run = (cmd) => new Promise(...)`.
        helpers = [(function.name, function.parameters, function.start, function.end) for function in ctx.bodies if function.name]
        helpers += [(arrow.group(1), arrow.group(2), arrow.end(), js.statement_end(code, arrow.end(), ctx.brackets)) for arrow in _CONCISE_ARROW.finditer(code)]
        for name, parameters, start, end in helpers:
            first = re.match(r"\s*([A-Za-z_$][\w$]*)", parameters)
            if not first or name in wrappers:
                continue
            index = bisect.bisect_left(offsets, start)
            inside = calls[index:bisect.bisect_left(offsets, end)][:50]
            if any(call.group(1) == first.group(1) for call in inside):
                wrappers.add(name)
    for match in re.finditer(rf"(?<![\w$])(?:this\s*\.\s*)?({'|'.join(map(re.escape, sorted(wrappers)))})\s*\(", code) if wrappers else ():
        close = ctx.brackets.get(match.end() - 1, -1)
        if close < 0 or _DEFINITION_TAIL.match(code, close + 1):
            continue  # the helper's own definition, `function run(cmd) {`
        spans = js.argument_spans(code, match.end() - 1, ctx.brackets, 1)
        if spans:
            yield from _built_command(ctx, match.start(), match.group(1), spans[0])
    for match in _SPAWN.finditer(code):
        spans = js.argument_spans(code, match.end() - 1, ctx.brackets, 3)
        if any(_SHELL_OPTION.search(code, start, end) for start, end in spans[1:]):
            yield from _built_command(ctx, match.start(), "This call", spans[0])


def _is_built(code: str, text: str, start: int, end: int) -> bool:
    value = code[start:end].strip()
    return (value.startswith("`") and "${" in text[start:end]) or ("+" in value and bool(re.search(r"['\"`]", value)))


def _built_command(ctx: Context, offset: int, name: str, span: tuple[int, int]) -> Iterator[tuple]:
    """A built command reaching a shell. It keeps the catalog's high confidence, which sends an agent back at Stop, only when the request is
    read in the call itself on the sink's line; through a variable, it's a medium lead."""
    code, text = ctx.source.code, ctx.source.text
    start, end = span
    argument = code[start:end].strip()
    built = _is_built(code, text, start, end)
    if not built and re.fullmatch(r"[A-Za-z_$][\w$]*", argument):
        declared = ctx.requests.declared_value(argument, start)
        built = bool(declared) and _is_built(code, text, *declared)
    if not built:
        return
    line = ctx.source.line_of(offset)
    read_here = any(ctx.source.line_of(start + read.start()) == line for read in _SOURCE.finditer(ctx.requests.view[start:end]))
    yield ("shell-injection", line, f"{name} runs its command through a shell, and the command is built from runtime values, so quotes, `;` or "
           "`$(...)` in one become commands. Pass an argument array to execFile or spawn.", {} if read_here else {"confidence": "medium"})


# ---------------------------------------------------------------- ownership and tenancy

_OWNER_FIELD = (r"(?:[\w$]*(?:[oO]wner|[aA]uthor|[uU]ser|[cC]reator|[cC]reatedBy|[aA]ccount|[tT]enant|[oO]rg|[oO]rganization|[wW]orkspace|[tT]eam|[mM]ember)"
                r"(?:Id|_id|ID|_ID)|(?:owner|author|user|tenant|org|creator))")
_OWNED = re.compile(rf"[\w$\])]\s*\??\.\s*{_OWNER_FIELD}\s*$")
_OPERAND_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$.?[]()")
_OPERAND_AFTER = re.compile(r"\s*([\w$.?\[\]()]{1,120})")
_EQUALITY = re.compile(r"[!=]==?")
_IDENTITY = re.compile(r"\b(?:req|request|ctx\.state|ctx)\s*\.\s*(?:user|auth|session|currentUser)\b|\bsession\b|\bcurrentUser\b|\bgetServerSession\b|"
                       r"\bauth\s*\(\s*\)|\bgetAuth\s*\(|@CurrentUser\b|\bres\.locals\.user\b|\bclaims\b|\bprincipal\b|\bjwt\b|\btoken\b", re.I)


def _operand_before(view: str, operator: int) -> tuple[str, int] | None:
    """The operand just left of a comparison, walked back over at most 120 characters, and where it starts."""
    end = operator
    while end > 0 and view[end - 1] in " \t":
        end -= 1
    start = end
    while start > max(0, end - 120) and view[start - 1] in _OPERAND_CHARACTERS:
        start -= 1
    return (view[start:end], start) if start < end else None


def owner_from_request(ctx: Context) -> Iterator[tuple]:
    """An ownership check that compares the record's owner with an id the client sent in the body, query or a header, which the client can set
    to the owner's. Only the session or a verified token says who is asking."""
    code, view = ctx.source.code, ctx.requests.view
    for match in _EQUALITY.finditer(code):
        left = _operand_before(view, match.start())
        right = _OPERAND_AFTER.match(view, match.end())
        if not left or not right:
            continue
        sides = [left, (right.group(1), right.start(1))]
        for (owned, owned_at), (other, other_at) in (sides, sides[::-1]):
            if not _OWNED.search(owned) or _IDENTITY.search(owned) or _IDENTITY.search(other) or ctx.requests.read(owned, owned_at)[2]:
                continue
            parts, _, direct = ctx.requests.read(other, other_at)
            if parts & {"body", "query", "header"} and direct:
                yield ("owner-from-request", ctx.source.line_of(match.start()), "This checks ownership against an id the client sent, which it can set "
                       "to the owner's. Compare with the signed-in user from the session or verified token.", {})
                break


_WRITE_BY = re.compile(r"\.\s*(?P<filtered>update|delete|upsert|destroy|updateOne|deleteOne|findOneAndUpdate|findOneAndDelete|findOneAndRemove)\s*(?:<[^()<>]{0,100}>\s*)?\(\s*(?=\{)"
                       r"|\.\s*(?P<byid>findByIdAndUpdate|findByIdAndDelete|findByIdAndRemove)\s*\("
                       r"|(?P<receiver>[\w$]+)\s*\.\s*(?P<repo>delete|update|softDelete|remove)\s*\(\s*(?![{\s)])"
                       r"|\.\s*(?P<knex>where)\s*\(\s*(?=\{)")
_REPOSITORY = re.compile(r"(?i:repo|repository|model|dao|table|collection)$|^[A-Z]")
_WHERE = re.compile(r"\bwhere\s*:\s*(?=\{)")
_ID_ONLY = {"id", "_id", "uuid", "slug"}
_KNEX_WRITE = re.compile(r"\)\s*\.\s*(?:update|del|delete)\s*\(")
_SCOPED_FIELD = re.compile(rf"(?<![\w$.]){_OWNER_FIELD}\s*[:=!]|\b(?:owner|author|tenant|org|organization|account|workspace|team|creator)(?:_?[iI]d)?\b")
_AUTHORIZES = re.compile(r"(?i:role|admin|permission|privilege|polic(?:y|ies)|abilit|(?<![Uu]n)authori[sz]|\bcan(?=[A-Z_(\s])|\bcannot\b|\bowns?\b|owner|\bacl\b|rbac|scope|"
                         r"grant|forbidden|\b403\b|staff|superuser|moderator)")
# Authorization for the whole file: a router-wide role middleware, or a role decorator on a NestJS controller class.
_FILE_AUTHORIZES = re.compile(r"\.\s*use\s*\([^;]{0,300}(?i:role|admin|permission|authori[sz]e|polic|abilit|rbac|\bacl\b)"
                              r"|@(?:Roles|Permissions|RequirePermissions|RequireRoles|CheckPolicies|Policies)\s*\([^)]{0,200}\)\s*(?:@[\w.]+\s*(?:\([^)]{0,200}\))?\s*)*(?:export\s+)?class\b")
_HANDLER_PARAMETERS = re.compile(r"\s*(?:async\s+)?\(?\s*(?:req|request|ctx|_req|_request)\b")
_NEXT_HANDLER = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_CALLER_SCOPED = re.compile(rf"(?<![\w$.]){_OWNER_FIELD}\s*:\s*(?:req|request|ctx\.state|session|user|currentUser|auth)\b")


def _handlers(ctx: Context, routes: list[tuple[int, int]]) -> list[tuple[int, int]]:
    code = ctx.source.code
    spans = list(routes)
    for function in ctx.bodies:
        if _HANDLER_PARAMETERS.match(function.parameters) or function.name in _NEXT_HANDLER or js.NEST_ROUTE.search(code, max(0, function.start - 600), function.start):
            spans.append((function.start, function.end))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def unscoped_writes(ctx: Context, routes: list[tuple[int, int]]) -> Iterator[tuple]:
    """A handler that knows who is asking, changing or deleting a record by the id in the request alone, with nothing in the handler checking
    the record is theirs: no owner or tenant in the filter, no comparison, no role. Any signed-in user can then change anyone's."""
    code, view, text = ctx.source.code, ctx.requests.view, ctx.source.text
    handlers = _handlers(ctx, routes)
    if not handlers or _FILE_AUTHORIZES.search(code):
        return
    starts = [start for start, _ in handlers]
    scoped_elsewhere = bool(_CALLER_SCOPED.search(view))
    for match in _WRITE_BY.finditer(code):
        index = bisect.bisect_right(starts, match.start()) - 1
        if index < 0 or handlers[index][1] <= match.start():
            continue
        if match.group("repo") and not _REPOSITORY.search(match.group("receiver")):
            continue
        id_span = _id_filter(ctx, match)
        if not id_span or not ctx.requests.read(view[id_span[0]:id_span[1]], id_span[0])[2]:
            continue
        start, end = handlers[index]
        handler = view[start:end]
        if not (_IDENTITY.search(handler) or scoped_elsewhere) or _SCOPED_FIELD.search(handler) or _AUTHORIZES.search(text[start:end]) or _AUTHORIZES.search(ctx.source.path):
            continue
        yield ("object-not-scoped", ctx.source.line_of(match.start()), "This changes the record with the id from the request and nothing else, and "
               "nothing in this handler checks that it belongs to the caller, so any signed-in user can change anyone's. Filter by the owner or tenant "
               "too, or check the record first.", {})


def _id_filter(ctx: Context, match: re.Match) -> tuple[int, int] | None:
    """Where the id is, when the write's filter is that id and nothing else."""
    code = ctx.source.code
    opening = match.end() - 1
    while opening > match.start() and code[opening] != "(":
        opening -= 1
    spans = js.argument_spans(code, opening, ctx.brackets, 2)
    if not spans:
        return None
    if match.group("byid") or match.group("repo"):
        return spans[0]
    if match.group("knex"):
        close = ctx.brackets.get(opening, -1)
        return _only_id(ctx, spans[0][0]) if close > 0 and _KNEX_WRITE.match(code, close) else None
    for start, end in spans:
        where = _WHERE.search(code, start, end)
        if where:
            return _only_id(ctx, where.end())
    if match.group("filtered") in ("updateOne", "deleteOne", "findOneAndUpdate", "findOneAndDelete", "findOneAndRemove"):
        return _only_id(ctx, spans[0][0])
    return None


def _only_id(ctx: Context, brace: int) -> tuple[int, int] | None:
    code = ctx.source.code
    while brace < len(code) and code[brace] in " \t\r\n":
        brace += 1
    if brace >= len(code) or code[brace] != "{":
        return None
    entries = js.argument_spans(code, brace, ctx.brackets, 3)
    if len(entries) != 1:
        return None
    start, end = entries[0]
    key, colon, _ = code[start:end].partition(":")
    if key.strip() not in _ID_ONLY:
        return None
    return (start + len(key) + 1, end) if colon else (start, end)


# ---------------------------------------------------------------- cache keys

_SCOPE_PARAMETER = re.compile(r"(?<![\w$])([\w$]*(?:[tT]enant|[oO]rg|[oO]rganization|[aA]ccount|[wW]orkspace|[uU]ser|[cC]ustomer|[cC]ompany|[tT]eam)(?:Id|_id|ID))\b")
_CACHE_CALL = re.compile(r"(?<![\w$])(?:this\s*\.\s*)?[\w$]*(?:[cC]ache|[rR]edis|[kK]v|[mM]emcache\w*|[lL]ru)\s*\.\s*(?:get|set|wrap|getOrSet|remember|fetch)\w*\s*"
                         r"(?:<[^()<>]{0,100}>\s*)?\(")


def cache_keys(ctx: Context) -> Iterator[tuple]:
    """A function scoped to a tenant or user, by its parameter, that caches its result under a key leaving that out, so the first caller's
    result is served to every other."""
    code = ctx.source.code
    for function in js.within_budget([function for function in ctx.bodies if _SCOPE_PARAMETER.search(function.parameters)], len(code)):
        scoped = [match.group(1) for match in _SCOPE_PARAMETER.finditer(function.parameters)]
        body = code[function.start:function.end]
        for call in _CACHE_CALL.finditer(code, function.start, function.end):
            spans = js.argument_spans(code, call.end() - 1, ctx.brackets, 1)
            key = _key_text(ctx, spans[0], function) if spans else None
            if key is None:
                continue
            missing = [name for name in scoped if not re.search(rf"\b{re.escape(name)}\b", key) and re.search(rf"\b{re.escape(name)}\b", body)]
            if len(missing) == len(scoped):
                yield ("cache-reads-user", ctx.source.line_of(call.start()), f"This function is scoped by {missing[0]}, but its cache key leaves it out, "
                       "so the first caller's result is served to everyone else. Put it in the key.", {})
                break


def _key_text(ctx: Context, span: tuple[int, int], function: js.Function) -> str | None:
    """A cache key's written-out text, from a template or concatenation here or in the `const` it names. None if it isn't built here."""
    code, text = ctx.source.code, ctx.source.text
    start, end = span
    argument = code[start:end].strip()
    if re.fullmatch(r"[A-Za-z_$][\w$]*", argument):
        declared = ctx.requests.declared_value(argument, start, start - function.start)
        if not declared:
            return None
        start, end = declared
        argument = code[start:end].strip()
    if argument.startswith("`") or ("+" in argument and re.search(r"['\"]", argument)):
        return text[start:end]
    return None


def findings(source: Source, brackets: dict[int, int], routes: list[tuple[int, int]], bodies: list[js.Function]) -> list[tuple]:
    ctx = context(source, brackets, bodies)
    return [*ssrf(ctx), *path_traversal(ctx), *server_html(ctx), *markup_sinks(ctx), *shell(ctx), *owner_from_request(ctx),
            *unscoped_writes(ctx, routes), *cache_keys(ctx)]
