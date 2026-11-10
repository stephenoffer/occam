"""JavaScript and TypeScript security settings and shapes that one pattern can't judge: cookies sent cross-site with no CSRF defense, CORS that
reflects any origin with credentials, webhooks that skip their signature, uploads with no size limit, stack traces in responses, keys written in
the source, Math.random for secrets, and merges that walk into __proto__."""

from __future__ import annotations

import bisect
import posixpath
import re
from collections.abc import Iterator

from . import js_syntax as js
from .source import Source

# ---------------------------------------------------------------- CSRF

_SAME_SITE_NONE = re.compile(r"""\bsameSite\s*:\s*['"`]none['"`]""", re.I)
_SETS_COOKIES = re.compile(r"\b(?:session|cookieSession|expressSession)\s*\(|\bcookie\s*:\s*\{|\.cookies?\s*\.?\s*set\s*\(|\bres\.cookie\s*\(")
_CSRF = re.compile(r"csrf|xsrf|csurf|lusca", re.I)


def csrf(source: Source) -> Iterator[tuple]:
    """A cookie sent on cross-site requests, SameSite=None, in a file that sets up the session and never mentions a CSRF defense. Any site can
    then make the browser send authenticated requests."""
    if _CSRF.search(source.text) or not _SETS_COOKIES.search(source.code):
        return
    for match in _SAME_SITE_NONE.finditer(source.text):
        if source.code[match.start()] == source.text[match.start()]:
            yield ("disabled-control", source.line_of(match.start()), "This cookie goes with cross-site requests (SameSite=None), and nothing here checks "
                   "a CSRF token, so another site can act as the signed-in user. Add a CSRF token check to state-changing routes, or use Lax.", {})


# ---------------------------------------------------------------- CORS

_CREDENTIALS = re.compile(r"\bcredentials\s*:\s*true\b")
_ORIGIN_KEY = re.compile(r"\borigin\s*(?::\s*(?:async\s+)?(?:function\b[^(]{0,40})?|(?=\())")
_REFLECTS = re.compile(r"\b[\w$]+\s*\(\s*null\s*,\s*(?:true\b|([\w$]+))")
_CHECKS_ORIGIN = re.compile(r"\.\s*(?:has|includes|test|match|endsWith|startsWith|indexOf|some|find)\s*\(|[!=]==?|\ballow", re.I)
_REFLECTED_HEADER = re.compile(r"""Access-Control-Allow-Origin['"]\s*,\s*(?:req|request|ctx)\s*\.\s*(?:headers\s*(?:\.\s*origin|\[\s*['"]origin['"]\s*\])|get\s*\(\s*['"]origin['"]|header\s*\(\s*['"]origin['"])""", re.I)
_CREDENTIALS_HEADER = re.compile(r"""Access-Control-Allow-Credentials['"]\s*,\s*['"]?true""", re.I)


def cors(source: Source, brackets: dict[int, int], bodies: list[js.Function]) -> Iterator[tuple]:
    """CORS that approves every origin by handing the caller's own back, with credentials on, so any site reads authenticated responses. An
    origin function that compares the origin with a list is the safe form."""
    code = source.code
    credentials = list(_CREDENTIALS.finditer(code))
    objects = js.innermost(js.blocks(code, brackets), [match.start() for match in credentials])
    starts = [function.start for function in bodies]
    for match in credentials:
        start, end = objects.get(match.start(), (0, 0))
        origin = _ORIGIN_KEY.search(code, start, end)
        if not origin:
            continue
        index = bisect.bisect_left(starts, origin.end())
        body = bodies[index] if index < len(bodies) and bodies[index].start < end else None
        parameter = re.match(r"\s*([\w$]+)", body.parameters) if body else None
        if body and body.start - origin.end() < 300:
            text = code[body.start:body.end]
        else:  # a concise arrow, `origin: (o, cb) => cb(null, o)`
            arrow = re.match(r"\s*\(?\s*([\w$]+)[^)=]{0,100}\)?\s*=>\s*([^\n]{1,200})", code[origin.end():end])
            if not arrow:
                continue
            parameter, text = arrow, arrow.group(2)
        reflected = _REFLECTS.search(text)
        if reflected and (reflected.group(1) is None or (parameter and reflected.group(1) == parameter.group(1))) and not _CHECKS_ORIGIN.search(text):
            yield ("permissive-cors", source.line_of(origin.start()), "This origin check approves every caller, and credentials are on, so any site can "
                   "read authenticated responses. Compare the origin with a list of the ones you serve.", {"severity": "high"})
    if _CREDENTIALS_HEADER.search(source.text):
        for match in _REFLECTED_HEADER.finditer(source.text):
            before = source.code[max(0, match.start() - 500):match.start()]
            if not _CHECKS_ORIGIN.search(before):
                yield ("permissive-cors", source.line_of(match.start()), "This sends back the caller's own Origin with credentials allowed, so any site "
                       "can read authenticated responses. Echo it only after checking it against a list.", {"severity": "high"})


# ---------------------------------------------------------------- webhooks

_VERIFIES = re.compile(r"hmac|signature|verify|constructEvent|timingSafeEqual|svix|x-hub-signature|stripe-signature|signing.?secret|webhook.?secret", re.I)
_SIGNATURE = r"(?:[\w$.]{0,60}?(?:[sS]ig(?![a-z])|[sS]ignature|[hH]mac|SIG|SIGNATURE|HMAC)[\w$.]{0,60})"  # bounded, so a long name can't backtrack
_SKIPPED_WHEN_ABSENT = re.compile(rf"""\bif\s*\(\s*(?:{_SIGNATURE}|(?:req|request)\s*\.\s*(?:get|header)\s*\(\s*['"][^'"\n]*(?i:sig|hmac)[^'"\n]*['"]\s*\)|"""
                                  r"""(?:req|request)\s*\.\s*headers\s*\[\s*['"][^'"\n]*(?i:sig|hmac)[^'"\n]*['"]\s*\])\s*&&\s*!\s*[\w$.]*(?i:verif|valid|match|check|compare|equal|safe)\w*\s*\(""")
_WEBHOOK_PATH = re.compile(r"webhook", re.I)
_POSTS = re.compile(r"\bexport\s+(?:async\s+)?function\s+POST\b|\bexport\s+const\s+POST\b|(?:^|[^\w$])(?:app|router|api|server|routes|fastify|\w+Router)\s*\.\s*post\s*\(", re.M)
_WEBHOOK_ROUTE = re.compile(r"""\.\s*post\s*\(\s*['"`][^'"`\n]*webhook""", re.I)


def webhooks(source: Source) -> Iterator[tuple]:
    """A webhook URL is public, so a handler that never checks the sender's signature, or checks it only when the header is there, acts on what
    anyone posts."""
    for match in _SKIPPED_WHEN_ABSENT.finditer(source.text):
        if source.code[match.start()] == source.text[match.start()]:
            yield ("webhook-unverified", source.line_of(match.start()), "The signature is checked only when its header is present, so a request "
                   "without one skips the check. Reject a request with no signature.", {})
    if _VERIFIES.search(source.text):
        return
    route = _WEBHOOK_ROUTE.search(source.text)
    if not route and _WEBHOOK_PATH.search(posixpath.basename(source.path) + " " + posixpath.dirname(source.path)):
        route = _POSTS.search(source.code)
    if route:
        yield ("webhook-unverified", source.line_of(route.start()), "This webhook handler never checks the sender's signature, so anyone who finds "
               "the URL can post events. Verify the signature over the raw body, and reject stale or repeated events.", {})


# ---------------------------------------------------------------- uploads

_UPLOADER = re.compile(r"(?<![\w$.])(?:multer|fileUpload|busboy|Busboy)\s*\(")


def uploads(source: Source, brackets: dict[int, int]) -> Iterator[tuple]:
    """multer, express-fileupload and busboy accept a file of any size unless given limits, so one request can fill memory or disk."""
    code = source.code
    for match in _UPLOADER.finditer(code):
        close = brackets.get(match.end() - 1, -1)
        if close < 0 or re.search(r"\blimits\b", code[match.end():close]) or re.match(r"\s*\)\s*\.\s*none\s*\(", code[close:close + 20]):
            continue
        yield ("upload-no-limit", source.line_of(match.start()), "This upload has no size limit, so one request can fill memory or disk. Set "
               "limits.fileSize and limits.files, and check the content, not only the file name.", {})


# ---------------------------------------------------------------- error details

_RESPONDER = re.compile(r"\b(?:res|reply|response)\s*(?:\.\s*(?:status|code)\s*\([^()]{0,100}\))?\s*\.\s*(?:json|send)\s*\(|\b(?:NextResponse|Response)\s*\.\s*json\s*\(")
_STACK = re.compile(r"\b(?:err|error|e|ex|exc|exception)\s*\??\.\s*stack\b")
_ENVIRONMENT_GUARD = re.compile(r"NODE_ENV|isDev\w*|isProd\w*|development|production|\bdebug\b|DEBUG|expose\w*|showStack|verbose", re.I)


def error_details(source: Source, brackets: dict[int, int]) -> Iterator[tuple]:
    """A response body carrying an error's stack trace, which shows a caller file paths and internals. One sent only in development is the
    usual safe form."""
    code = source.code
    for match in _RESPONDER.finditer(code):
        close = brackets.get(match.end() - 1, -1)
        if close < 0 or close - match.end() > 3000 or not _STACK.search(code, match.end(), close):
            continue
        if not _ENVIRONMENT_GUARD.search(source.text, max(0, match.start() - 400), close):
            yield ("error-details-exposed", source.line_of(match.start()), "This response sends the error's stack trace to the caller, which shows "
                   "file paths and internals. Log it, and return a short message with an id to look it up.", {})


# ---------------------------------------------------------------- keys in the source

_KEYED = re.compile(r"(?<![\w$.])(?:crypto\s*\.\s*)?(?:(?P<cipher>createCipheriv|createDecipheriv)|(?P<hmac>createHmac))\s*\(")
_LITERAL_KEY = re.compile(r"""\s*(?:Buffer\s*\.\s*from\s*\(\s*)?(['"`])([^'"`\n]{8,})\1""")


_DECLARED = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=;\n]{1,100})?=")


def literal_keys(source: Source, brackets: dict[int, int]) -> Iterator[tuple]:
    """A cipher or HMAC key written in the source, directly or in a constant, so anyone with the code or a copy of it has the key."""
    code, text = source.code, source.text
    declared: dict[str, list[int]] | None = None
    for match in _KEYED.finditer(code):
        spans = js.argument_spans(code, match.end() - 1, brackets, 2)
        if len(spans) < 2:
            continue
        start, end = spans[1]
        key = code[start:end].strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", key):
            if declared is None:  # every declaration's value, found once, so many keyed calls stay linear
                declared = {}
                for declaration in _DECLARED.finditer(code):
                    declared.setdefault(declaration.group(1), []).append(declaration.end())
            ends = declared.get(key, [])
            index = bisect.bisect_left(ends, start) - 1
            if index < 0:
                continue
            start = ends[index]
        literal = _LITERAL_KEY.match(text, start)
        if literal and "${" not in literal.group(2):
            yield ("key-in-source", source.line_of(match.start()), "This key is written in the source, so anyone with the code or a copy of it can "
                   "decrypt or forge what it protects. Load it from a secret store or the environment, and rotate it.", {})


# ---------------------------------------------------------------- randomness

_RANDOM = re.compile(r"\bMath\.random\s*\(\s*\)")
_SECRET_ON_LINE = re.compile(r"(?i:token|secret|password|session|nonce|salt|otp)\w*[^\n]{0,60}Math\.random\(\)|Math\.random\(\)[^\n]{0,60}(?i:token|secret|password|nonce|salt)")
# A function named for the secret it makes, by its last word: generateSessionId, makeResetToken, newNonce. Not sessionColor or scheduleSessionRefresh.
_SECRET_MAKER = re.compile(r"(?i)(?:token|secret|password|passwd|passphrase|nonce|salt|otp|sid|session_?id|(?:api|secret|access|signing)_?key|csrf\w*|"
                           r"(?:reset|verif\w*|confirm\w*|invite|auth|login|otp|one_?time)_?code|pin)s?$")
_ASSIGNED = re.compile(r"(?:\b(?:const|let|var)\s+)?([A-Za-z_$][\w$]*)\s*(?:\+=|=(?![=>]))")


def randomness(source: Source, bodies: list[js.Function]) -> Iterator[tuple]:
    """Math.random is predictable, so a token, session id or reset code made from it can be guessed. Named so on the line, or the value a
    function named for one, such as generateSessionId, returns: on its return line, or in a variable it returns. A shuffle, a delay or a
    color picked at random in such a file isn't the secret."""
    code = source.code
    matches = list(_RANDOM.finditer(code))
    enclosing = js.enclosing_function(bodies, [match.start() for match in matches])
    reported = set()
    for match in matches:
        line = source.line_of(match.start())
        if line in reported:
            continue
        function = enclosing.get(match.start())
        if _SECRET_ON_LINE.search(source.line_text(line)) or (function and _SECRET_MAKER.search(function.name) and _returned(source, function, line)):
            reported.add(line)
            yield "insecure-random", line, None, {}


def _returned(source: Source, function: js.Function, line: int) -> bool:
    """The random value on this line is what the function returns: the line returns it, or assigns a name a later return uses."""
    start = source.line_starts[line - 1]
    statement = source.code[start:source.line_starts[line] if line < len(source.line_starts) else len(source.code)]
    if re.match(r"\s*return\b", statement):
        return True
    assigned = _ASSIGNED.search(statement)
    # Raw text, since a template such as `${time}${rand}` is blank in the code view.
    return bool(assigned) and bool(re.search(rf"\breturn\b[^;\n]*\b{re.escape(assigned.group(1))}\b", source.text[start:function.end]))


# ---------------------------------------------------------------- prototype pollution

_COMPUTED_WRITE = re.compile(r"[\w$\]]\s*\[\s*([\w$]+(?:\s*\[[^\[\]\n]{1,40}\])?)\s*\]\s*(?:\?\?|\|\||&&)?=(?!=)")
_KEY_LOOP = re.compile(r"\bfor\s*\(\s*(?:const|let|var)\s+([\w$]+)\s+in\b|\bfor\s*\(\s*(?:const|let|var)\s+(?:\[\s*)?([\w$]+)[^)]{0,40}\bof\s+Object\s*\.\s*(?:keys|entries)\s*\("
                       r"|\bObject\s*\.\s*(?:keys|entries)\s*\([^()]{0,100}\)\s*\.\s*forEach\s*\(\s*(?:function\s*)?\(?\s*(?:\[\s*)?([\w$]+)")
_PATH_WALK = re.compile(r"\b([\w$]+)\s*=\s*\1\s*\[\s*([A-Za-z_$][\w$]*)\s*\]")
_GUARDED = re.compile(r"__proto__|\bprototype\b|\bconstructor\b|hasOwn|isSafe\w*|Object\s*\.\s*create\s*\(\s*null|(?i:blocked|forbidden|unsafe|denied|reserved|dangerous|banned|illegal)\w*")


def prototype_pollution(source: Source, bodies: list[js.Function]) -> Iterator[tuple]:
    """A function that walks keys it was given into nested objects, by recursing on `target[key]` or stepping `cur = cur[key]` along a dotted
    path, with no guard for `__proto__`. A key of "__proto__" then writes to Object.prototype, which every object in the process shares."""
    if "__proto__" in source.text:
        return
    code = source.code
    for function in js.within_budget(bodies, len(code)):
        body = code[function.start:function.end]
        writes = list(_COMPUTED_WRITE.finditer(body))
        if not writes or _GUARDED.search(body):
            continue
        keys = {name for match in _KEY_LOOP.finditer(body) for name in match.groups() if name}
        recursive = bool(function.name) and re.search(rf"(?<![\w$.]){re.escape(function.name)}\s*\(\s*[\w$]+\s*\[", body)
        walks = re.search(r"\.\s*split\s*\(", body) and any(re.search(rf"\b{re.escape(walk.group(1))}\s*\[(?:[^\[\]\n]|\[[^\[\]\n]{{0,40}}\]){{1,80}}\]\s*(?:\?\?|\|\||&&)?=(?!=)", body)
                                                            for walk in _PATH_WALK.finditer(body))
        hit = next((write for write in writes if (recursive and write.group(1) in keys) or walks), None)
        if hit:
            yield ("prototype-pollution", source.line_of(function.start + hit.start()), "This walks keys it was given into nested objects with no guard "
                   "for __proto__, so a key of \"__proto__\" writes to Object.prototype, which every object shares. Skip __proto__, constructor and "
                   "prototype, or build on Object.create(null).", {})


def findings(source: Source, brackets: dict[int, int], bodies: list[js.Function]) -> list[tuple]:
    return [*csrf(source), *cors(source, brackets, bodies), *webhooks(source), *uploads(source, brackets), *error_details(source, brackets),
            *literal_keys(source, brackets), *randomness(source, bodies), *prototype_pollution(source, bodies)]
