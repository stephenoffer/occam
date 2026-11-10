"""Java and Kotlin checks: the sinks a security reviewer names in Spring and plain JDBC code, and the data rows: writes outside a
transaction, read-modify-write, check-then-insert, retried effects, acknowledged-before-done messages, leased locks and shared state.

They report under the ids the other languages use where the failure is the same. There is no Java corpus on the machine they were
written on, so each stays narrow: a framework's own spelling of the failure, or a sink whose argument is built in the same method.
None is high severity with high confidence, so none sends an agent back at Stop on a guess (DESIGN.md no-new-send-backs).
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from . import rules_braced as braced
from .py_helpers import PLACEHOLDER_NAME, PUBLIC_ROUTE, _has_sql
from .source import Source

_MEDIUM = {"confidence": "medium"}
_STRING = r'"(?:[^"\\\n]|\\.)*"'
_STRING_RE = re.compile(_STRING)
_SPRING_BEAN = re.compile(r"@(?:Service|Component|RestController|Controller|Repository|Configuration|Singleton|ApplicationScoped|Named)\b")


def _preamble(code: str, head: int) -> str:
    """The annotations and modifiers before a declaration: back to the previous statement, block or member."""
    window = max(0, head - 2000)
    start = max(code.rfind(";", window, head), code.rfind("}", window, head), code.rfind("{", window, head)) + 1
    return code[max(start, window):head]


def _class_start(code: str) -> int:
    match = re.search(r"\b(?:class|interface|object|enum|record)\s+\w+", code)
    return match.start() if match else -1


def _class_preamble(code: str) -> str:
    start = _class_start(code)
    return _preamble(code, start) if start >= 0 else ""


def _field_types(code: str) -> dict[str, str]:
    """Field and parameter names with their declared types, as `private final OrderRepository orders;`."""
    found = {}
    for match in re.finditer(r"(?:private|protected|public|final|val|var)\s+(?:final\s+)?(?:(\w+)(?:<[^;=(){}]{0,200}>)?\s+(\w+)\s*[;=]|(\w+)\s*:\s*(\w+))", code):
        if match.group(1):
            found[match.group(2)] = match.group(1)
        else:
            found[match.group(3)] = match.group(4)
    for match in re.finditer(r"[(,]\s*(?:final\s+)?(\w+)(?:<[^()]{0,200}>)?\s+(\w+)\s*(?=[,)])", code):
        found.setdefault(match.group(2), match.group(1))
    return found


class _Method:
    def __init__(self, source: Source, body: braced.Body, pairs: dict[int, int], budget: braced.Budget) -> None:
        self.source, self.body, self.pairs, self.budget = source, body, pairs, budget
        self.code = source.code[body.start:body.end]
        self.offset = body.start
        before = _preamble(source.code, body.head)
        self.preamble_start = body.head - len(before)
        self.preamble = before + source.code[body.head:body.start]

    def line(self, relative: int) -> int:
        return self.source.line_of(self.offset + relative)


# ---------------------------------------------------------------- SQL

_SQL_CALL = re.compile(r"\.(query|queryForObject|queryForList|queryForMap|queryForRowSet|queryForStream|queryForLong|queryForInt|update|batchUpdate|execute|executeQuery"
                       r"|executeUpdate|executeLargeUpdate|addBatch|prepareStatement|prepareCall|createQuery|createNativeQuery|createSQLQuery|sql|fetch|resultQuery|createUpdate)\s*\(")
# What rules_text's sql-injection pattern already reports: a literal concatenated inside the call itself.
_INLINE_SQL = re.compile(r"""\.(?:executeQuery|executeUpdate|prepareStatement|createQuery)\(\s*"[^"\n]*"\s*\+""")
_NUMERIC_DECLARATION = re.compile(r"\b(?:int|long|short|byte|double|float|boolean|Integer|Long|Short|Double|Float|Boolean|BigDecimal|BigInteger|UUID|LocalDate|LocalDateTime|Instant)\s+(\w+)\b")
# Operands that can't carry text from outside, in the code view (string contents blanked, quotes kept): constants, sizes, enum names,
# and a literal repeated, as String.join(",", Collections.nCopies(n, "?")), "?,".repeat(n) or xs.stream().map(x -> "?").collect(joining(",")).
_SAFE_OPERAND = re.compile(r"[A-Z][A-Z0-9_]*|(?:\w+\.)+[A-Z][A-Z0-9_]*|\w+\.(?:size|length|ordinal|name)\(\)|\w+\.length|\d[\w.]*|'.'"
                           r"|(?:String\.join\(\s*\"[^\"]*\"\s*,\s*)?Collections\.nCopies\(.*,\s*\"[^\"]*\"\s*\)\s*\)?|\"[^\"]*\"\s*\.\s*repeat\(.*\)"
                           r"|.*\.\s*map\(\s*\w+\s*->\s*\"[^\"]*\"\s*\)\s*\.\s*collect\(\s*Collectors\.joining\([^()]*\)\s*\)"
                           r"|(?:Integer|Long|String)\.(?:toString|valueOf)\(\s*\w+\.size\(\)\s*\)")
_JOINED_LIST = re.compile(r"String\.join\(\s*\"[^\"]*\"\s*,\s*(\w+)\s*\)|(\w+)\s*\.\s*stream\(\)\s*\.\s*collect\(\s*Collectors\.joining\([^()]*\)\s*\)")
_EMPTY_COLLECTION = re.compile(r"new\s+[\w.]+(?:<[^()]*>)?\(\s*\)")
_DEPTH = 3


class _Sql:
    """Is this expression SQL text with a runtime value spliced in? Follows a name back to what built it, within the method. What can't
    be seen, such as a list filled elsewhere, counts as safe, so a guess never blocks gate."""

    def __init__(self, method: _Method) -> None:
        self.method, self.source = method, method.source
        self.numeric = {match.group(1) for match in _NUMERIC_DECLARATION.finditer(method.body.params + method.code)}
        self.params = set(re.findall(r"\w+", method.body.params))
        self._seen: dict[tuple[str, int], list[tuple[str, int, int]]] = {}
        self._checked: dict[tuple[str, int], bool] = {}

    def _assignments(self, name: str, before: int) -> list[tuple[str, int, int]]:
        """(kind, start, end) of what `name` is given before this offset: `set` for = (and a declaration), `add` for +=, `append` for each
        argument of name.append(...) and the appends chained after it, and `item` for each argument of name.add(...)."""
        if (name, before) in self._seen:
            return self._seen[(name, before)]
        code, pairs = self.source.code, self.method.pairs
        found: list[tuple[str, int, int]] = []
        self._seen[(name, before)] = found  # filled below, and what a recursive look at the same name sees meanwhile
        if not self.method.budget.spend(before - self.method.offset):
            return found
        escaped = re.escape(name)
        pattern = re.compile(rf"(?<![\w.]){escaped}\s*(\+=|=(?!=))|(?<![\w.]){escaped}\s*\.\s*(?:(append|insert)|add|addAll|addFirst|addLast|push|offer)\s*\(")
        for match in pattern.finditer(code, self.method.offset, before):
            if match.group(1):
                end = code.find(";", match.end(), before)
                found.append(("add" if match.group(1) == "+=" else "set", match.end(), before if end < 0 else end))
                continue
            if not match.group(2):
                found += [("item", a, b) for a, b in braced.arguments(code, match.end() - 1, pairs)[-1:]]
                continue
            opening = match.end() - 1
            while opening > 0:
                closing = pairs.get(opening, -1)
                if closing < 0 or closing > before:
                    break
                args = braced.arguments(code, opening, pairs)
                if args:
                    found.append(("append", *args[-1]))
                if len(found) > 200:
                    return found
                chained = re.match(r"\s*\.\s*(?:append|insert)\s*\(", code[closing + 1:closing + 200])
                opening = closing + chained.end() if chained else -1
        return found

    def _value_safe(self, start: int, end: int, before: int, depth: int) -> bool:
        """One value given to a name or put in a list: literal text, a safe operand, or something built with nothing unsafe spliced in."""
        code = self.source.code
        value = code[start:end].strip()
        if not value or _EMPTY_COLLECTION.fullmatch(value):
            return True
        if re.fullmatch(r"(?:new\s+[\w.]+(?:<[^()]*>)?\(\s*)?(?:(?:List|Set)\.of|Arrays\.asList)\(.*\)\s*\)?", value, re.S):
            listed = re.compile(r"\b(?:of|asList)\(").search(code, start, end)  # check each element
            return all(self._value_safe(a, b, before, depth + 1) for a, b in braced.arguments(code, listed.end() - 1, self.method.pairs))
        if "+" in value or "String.format(" in value:
            return not self.built(start, end, depth + 1)[1]
        return self.safe(value, before, depth + 1)

    def _allowlisted(self, name: str, before: int) -> bool:
        """Checked against a fixed set before use: a contains or containsKey, a switch, Enum.valueOf, or an allow or valid helper."""
        if (name, before) in self._checked:
            return self._checked[(name, before)]
        self._checked[(name, before)] = False
        if not self.method.budget.spend(before - self.method.offset):
            return False
        escaped = re.escape(name)
        checked = re.compile(rf"\b[\w.]+\s*\.\s*contains(?:Key)?\(\s*{escaped}\s*\)|\bswitch\s*\(\s*{escaped}\s*\)|\b\w+\.valueOf\(\s*{escaped}\s*\)"
                             rf"|\b\w*(?:[Aa]llow|[Vv]alid|[Ss]ortable|[Ww]hitelist|[Pp]ermitted)\w*\(\s*{escaped}\s*\)")
        self._checked[(name, before)] = bool(checked.search(self.source.code, self.method.offset, before))
        return self._checked[(name, before)]

    def safe(self, operand: str, before: int, depth: int) -> bool:
        operand = operand.strip()
        while operand.startswith("(") and operand.endswith(")"):
            operand = operand[1:-1].strip()
        if not operand or operand[0] in "\"'" or _SAFE_OPERAND.fullmatch(operand) or operand in self.numeric:
            return True
        if depth >= _DEPTH:
            return False
        joined = _JOINED_LIST.fullmatch(operand)
        if joined:
            return all(self._value_safe(a, b, before, depth) for _, a, b in self._assignments(joined.group(1) or joined.group(2), before))
        if not re.fullmatch(r"\w+", operand):
            return False
        if self._allowlisted(operand, before):
            return True
        spans = self._assignments(operand, before)
        if operand in self.params or not spans:
            return bool(PLACEHOLDER_NAME.fullmatch(operand)) and all(self._value_safe(a, b, before, depth) for _, a, b in spans)
        return all(self._value_safe(a, b, before, depth) for _, a, b in spans)

    def _formatted(self, opening: int, before: int, depth: int) -> tuple[bool, bool]:
        code, text = self.source.code, self.source.text
        args = braced.arguments(code, opening, self.method.pairs)
        if not args:
            return False, False
        form = braced.literal_text(text, *args[0], _STRING_RE)
        verbs = [verb for verb in re.findall(r"%[-#+ 0,(]*\d*(?:\.\d+)?([a-zA-Z%])", form) if verb != "%"]
        spliced = any(verb in "sS" and not self.safe(code[a:b], before, depth) for verb, (a, b) in zip(verbs, args[1:]))
        return _has_sql(form), spliced

    def built(self, start: int, end: int, depth: int = 0) -> tuple[bool, bool]:
        code, text = self.source.code, self.source.text
        expression = code[start:end].strip()
        literals = braced.literal_text(text, start, end, _STRING_RE)
        sql, spliced = _has_sql(literals), False
        for call in re.finditer(r"\bString\.format\(", code[start:end]):
            found_sql, found_spliced = self._formatted(start + call.end() - 1, start, depth)
            sql, spliced = sql or found_sql, spliced or found_spliced
        if self.source.language == "kotlin" and re.search(r"\$\{|\$[a-zA-Z_]", literals):
            spliced = spliced or bool(re.search(r"\$\{?(?!(?:[A-Z][A-Z0-9_]*|placeholders?|marks?)\b)[a-zA-Z_]", literals))
        if literals and "+" in code[start:end]:
            spliced = spliced or any(not self.safe(code[a:b], start, depth) for a, b in braced.parts(code, start, end, "+") if "String.format(" not in code[a:b])
        name = re.fullmatch(r"(\w+)(?:\.toString\(\))?", expression)
        if depth < _DEPTH and name:
            for kind, value_start, value_end in self._assignments(name.group(1), start):
                if kind == "item":
                    continue
                found_sql, found_spliced = self.built(value_start, value_end, depth + 1)
                value = code[value_start:value_end].strip()
                if kind != "set" and not found_spliced and not _STRING_RE.fullmatch(text[value_start:value_end].strip()):
                    found_spliced = "+" not in value and "String.format(" not in value and not self.safe(value, start, depth + 1)
                if kind == "set" and re.match(r"new\s+StringBuilder\(\s*\w+\s*\)", value):
                    found_spliced = found_spliced or not self.safe(re.match(r"new\s+StringBuilder\(\s*(\w+)", value).group(1), start, depth + 1)
                sql, spliced = sql or found_sql, spliced or found_spliced
        return sql, spliced


_MYBATIS_SUBSTITUTION = re.compile(r"@(?:Select|Update|Insert|Delete)\(\s*(?:\{\s*)?(?:" + _STRING + r"\s*[,+]?\s*){0,20}?\"[^\"\n]*\$\{")


def _sql(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    code = source.code
    bodies = [method.body for method in methods]
    starts = [body.start for body in bodies]
    by_body = {method.body: method for method in methods}
    budget = methods[0].budget if methods else braced.Budget(code)
    whole = None  # a Kotlin expression body, `fun f() = jdbc.query(...)`, or code outside any method
    readers: dict[braced.Body, _Sql] = {}
    for match in _SQL_CALL.finditer(code):
        if budget.left <= 0:
            return
        if _INLINE_SQL.match(source.text, match.start()):
            continue
        body = braced.enclosing(bodies, match.start(), starts)
        if body is None:
            whole = whole or _Method(source, braced.Body("", 0, 0, len(code), ""), methods[0].pairs if methods else braced.pairs(code), budget)
            method = whole
        else:
            method = by_body[body]
        reader = readers.get(method.body)
        if reader is None:
            reader = readers[method.body] = _Sql(method)
        args = braced.arguments(code, match.end() - 1, method.pairs)
        if not args:
            continue
        start, end = braced.strip(code, args[0])
        sql, spliced = reader.built(start, end)
        if sql and spliced:
            expression = code[start:end].strip()
            how = "built here" if re.search(r"\+|String\.format\(|\$", source.text[start:end]) else f"built earlier into {expression.split('.')[0]}"
            yield ("sql-injection", source.line_of(match.start()), f".{match.group(1)}() runs SQL {how} with a runtime value spliced into the text. "
                   "Bind values with ? or named parameters, and check identifiers such as a sort column against a fixed list.", _MEDIUM)
    for match in _MYBATIS_SUBSTITUTION.finditer(source.text):
        yield ("sql-injection", source.line_of(match.start()), "MyBatis pastes ${...} into the SQL text as it is. Use #{...}, which binds the value, "
               "and check identifiers against a fixed list.", _MEDIUM)


# ---------------------------------------------------------------- shell, deserialization, TLS, passwords

_SHELL = re.compile(r"""(?:\bnew\s+ProcessBuilder|(?<![\w.])ProcessBuilder|\.command)\(\s*(?:(?:List\.of|Arrays\.asList|listOf|mutableListOf)\(\s*)?"""
                    r'''"(?:/usr)?(?:/bin/)?(?:ba|z|da|k)?sh"\s*,\s*"-\w*c"\s*,\s*''')
_LITERAL_ARGUMENT = re.compile(rf"(?:{_STRING})\s*[,)]")
_PATTERNS: list[tuple[str, re.Pattern, str, dict]] = [
    ("unsafe-deserialize", re.compile(r"\.enableDefaultTyping\w*\(|\bLaissezFaireSubTypeValidator\.instance\b"),
     "Jackson's default typing with no allow-list lets JSON name any class on the classpath to build, the gadget chains behind Jackson's "
     "deserialization CVEs. Use @JsonTypeInfo(use = NAME) with @JsonSubTypes, or a BasicPolymorphicTypeValidator that allows your own packages.", _MEDIUM),
    ("tls-disabled", re.compile(r"\bvoid\s+checkServerTrusted\s*\([^(){}]{0,300}\)\s*(?:throws\s+[\w.,\s]{1,200}?)?\{\s*(?:return\s*;\s*)?\}"
                                r"|\bfun\s+checkServerTrusted\s*\([^(){}]{0,300}\)\s*(?:\{\s*\}|=\s*Unit\b)"),
     "This trust manager accepts every server certificate, so anyone on the path can impersonate the server. Use the default trust store, or "
     "load the private CA into a KeyStore and trust that.", _MEDIUM),
    ("tls-disabled", re.compile(r"(?:[Hh]ostnameVerifier\w*|HostnameVerifier\s+\w+\s*=)\s*\(?\s*\(\s*\w*\s*,\s*\w*\s*\)\s*->\s*true\b"
                                r"|\bboolean\s+verify\s*\(\s*(?:final\s+)?String\s+\w+\s*,\s*(?:final\s+)?SSLSession\s+\w+\s*\)\s*\{\s*return\s+true\s*;\s*\}"
                                r"|\bhostnameVerifier\s*\{\s*_\s*,\s*_\s*->\s*true\s*\}|\bNoopHostnameVerifier\.INSTANCE\b|\bnew\s+NoopHostnameVerifier\(|\bALLOW_ALL_HOSTNAME_VERIFIER\b"
                                r"|\bnew\s+AllowAllHostnameVerifier\(|\bTrustAllStrategy\.INSTANCE\b|\bnew\s+TrustAllStrategy\(|\bnew\s+TrustSelfSignedStrategy\(|\bInsecureTrustManagerFactory\.INSTANCE\b"),
     "This accepts any certificate or any host name, so TLS no longer proves who is on the other end. Keep the default verifier, and trust "
     "a private CA explicitly if you need one.", _MEDIUM),
    ("weak-password-hash", re.compile(r"\bNoOpPasswordEncoder\.getInstance\(|\b(?:new\s+)?(?:StandardPasswordEncoder|Md4PasswordEncoder|LdapShaPasswordEncoder|MessageDigestPasswordEncoder)\("
                                      r"|\bDigestUtils\.(?:md5|sha1|sha256|sha512|sha)\w*\(\s*[\w.]*(?i:password|passwd|pwd)"
                                      r"|\.digest\(\s*[\w.]*(?i:password|passwd|pwd)\w*(?:\.getBytes\([^()]*\))?\s*\)"),
     "Passwords stored this way are plaintext or a fast hash, so a leaked table gives up every password. Use BCryptPasswordEncoder, Argon2 or "
     "scrypt, or DelegatingPasswordEncoder to migrate.", _MEDIUM),
    ("unacknowledged-write", re.compile(r"\bWriteConcern\.(?:UNACKNOWLEDGED|ERRORS_IGNORED)\b|\bnew\s+WriteConcern\(\s*0\s*\)|\bACKS_CONFIG\s*,\s*\"0\"|\"acks\"\s*,\s*\"0\""),
     "Writes here don't wait for the server to confirm them, so a write that fails is reported as saved. Wait for acknowledgement wherever the "
     "caller is told it succeeded.", {}),
]


def _patterns(source: Source) -> Iterator[tuple]:
    for rule, pattern, message, overrides in _PATTERNS:
        view = source.text if rule == "unacknowledged-write" else source.code
        for match in pattern.finditer(view):
            if source.code[match.start()] == source.text[match.start()]:
                yield rule, source.line_of(match.start()), message, overrides
    for match in _SHELL.finditer(source.text):
        if source.code[match.start()] == source.text[match.start()] and not _LITERAL_ARGUMENT.match(source.text, match.end()):
            yield ("shell-injection", source.line_of(match.start()), "This runs a command line built at runtime through a shell, so a quote, ; or $( ) "
                   "in any value becomes shell syntax. Pass the program and each value as separate arguments, with no shell.", _MEDIUM)


# ---------------------------------------------------------------- Spring Security settings

_CSRF_OFF = re.compile(r"\.csrf\(\s*(?:\w+\s*->\s*\w+\s*\.\s*disable\(\)|AbstractHttpConfigurer::disable|CsrfConfigurer<\w*>::disable|CsrfConfigurer::disable)\s*\)"
                       r"|\.csrf\(\)\s*\.disable\(\)|\bcsrf\s*\{\s*disable\(\)\s*\}")
_STATELESS = re.compile(r"\bSessionCreationPolicy\.STATELESS\b")
_ANY_ORIGIN_PATTERN = re.compile(r"""(?:setAllowedOriginPatterns|allowedOriginPatterns|addAllowedOriginPattern)\(\s*(?:(?:List\.of|Arrays\.asList|Collections\.singletonList|listOf)\(\s*)?"(?:\*|https?://\*)"\s*""")
_CREDENTIALS = re.compile(r"(?:setAllowCredentials|allowCredentials)\(\s*true\s*\)|allowCredentials\s*=\s*\"true\"|allowCredentials\s*=\s*true")
_CROSS_ORIGIN = re.compile(r"""@CrossOrigin\([^()]{0,400}?originPatterns\s*=\s*\{?\s*"\*"[^()]{0,400}?allowCredentials\s*=\s*"true"|@CrossOrigin\([^()]{0,400}?allowCredentials\s*=\s*"true"[^()]{0,400}?originPatterns\s*=\s*\{?\s*"\*\"""")
_ORIGIN_SUFFIX = re.compile(r"""\b(\w{0,40}?(?i:origin|host)\w{0,40}(?:\(\))?)\s*\.\s*(endsWith|contains)\(\s*("(?:[^"\\\n]|\\.)*"|\w+)\s*\)""")


def _spring_security(source: Source) -> Iterator[tuple]:
    text, code = source.text, source.code
    if not _STATELESS.search(code):
        for match in _CSRF_OFF.finditer(code):
            yield ("disabled-control", source.line_of(match.start()), "CSRF protection is off, and nothing here makes the API stateless, so a browser "
                   "sends the session cookie with a forged cross-site POST. Keep it on for cookie sessions, or set SessionCreationPolicy.STATELESS and "
                   "accept only bearer tokens.", _MEDIUM)
    origin = _ANY_ORIGIN_PATTERN.search(text)
    if origin and _CREDENTIALS.search(text):
        yield ("permissive-cors", source.line_of(origin.start()), "Origin pattern * with credentials makes Spring echo any Origin with "
               "Access-Control-Allow-Credentials, so every site can call the API as the user. List the origins you serve.", {"severity": "high"})
    for match in _CROSS_ORIGIN.finditer(text):
        yield ("permissive-cors", source.line_of(match.start()), "Origin pattern * with credentials lets every site call this as the user. List the "
               "origins you serve.", {"severity": "high"})
    if re.search(r"Access-Control-Allow-Origin|CorsConfiguration|CorsFilter|addCorsMappings", text):
        values = {match.group(1): match.group(2) for match in re.finditer(rf"\b(\w+)\s*=\s*({_STRING})\s*;", text)}
        for match in _ORIGIN_SUFFIX.finditer(text):
            value = values.get(match.group(3), match.group(3))
            if code[match.start()] != text[match.start()] or not value.startswith('"'):
                continue
            literal = value[1:-1]
            if match.group(2) == "contains" or not literal.startswith((".", "://")):
                yield ("permissive-cors", source.line_of(match.start()), f"{match.group(2)}({literal!r}) lets any origin that merely ends with or contains "
                       f"it through, such as https://evil{literal.lstrip('.')}. Compare the whole origin against a fixed set.", {})


# ---------------------------------------------------------------- authorization

_GRANTS = re.compile(r"\breturn\s+(?:new\s+AuthorizationDecision\(\s*true\s*\)|AuthorizationDecision\(\s*true\s*\)|(?:AccessDecisionVoter\.)?ACCESS_GRANTED|true)\s*;?")
# An authorization decision, by name. `verifyNotRevoked` returning true when the revocation isn't found is a lookup, not a grant.
_ALLOW_METHOD = re.compile(r"(?:is|has|can)(?:Allowed|Authori[sz]ed|Permitted|Granted|Member|Access|Permission)\w*$"
                           r"|(?:hasPermission|hasAccess|canAccess|authori[sz]e|permits?|vote|decide|check(?:Access|Permission|Authori[sz]ation))\w*$")
_ABSENCE_CAUGHT = re.compile(r"NotFound|NoSuch|Missing|Absent|EmptyResult")
_CATCH = re.compile(r"\bcatch\s*\([^(){}]{1,300}\)\s*\{")
_ROUTE = re.compile(r"@(?:Get|Post|Put|Patch|Delete|Request)Mapping\b|@(?:GET|POST|PUT|PATCH|DELETE)\b")
_MUTATES = re.compile(r"@(?:Post|Put|Patch|Delete)Mapping\b|@(?:POST|PUT|PATCH|DELETE)\b|RequestMethod\.(?:POST|PUT|PATCH|DELETE)\b")
_GUARD = re.compile(r"@(?:PreAuthorize|PostAuthorize|Secured|RolesAllowed|PermitAll|DenyAll|RequiresPermissions|RequiresRoles)\b")


def _fail_open(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    code = source.code
    bodies = [method.body for method in methods]
    starts = [body.start for body in bodies]
    budget = methods[0].budget if methods else braced.Budget("")
    for match in _CATCH.finditer(code):
        end = methods[0].pairs.get(match.end() - 1, -1) if methods else -1
        grant = _GRANTS.search(code, match.end(), end) if end > 0 and budget.spend(end - match.end()) else None
        if not grant:
            continue
        method = braced.enclosing(bodies, match.start(), starts)
        explicit = not re.match(r"return\s+true\b", grant.group(0))
        if explicit or (method and _ALLOW_METHOD.match(method.name) and not _ABSENCE_CAUGHT.search(match.group(0))):
            yield ("fail-open", source.line_of(grant.start()), "When the check throws, this grants access, so an outage of the cache or the service "
                   "it asks opens the door to everyone. Deny on error, and let the caller retry.", _MEDIUM)


def _missing_auth(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    if _GUARD.search(_class_preamble(source.code)):
        return
    routes = []
    for method in methods:
        preamble = method.preamble
        route = _ROUTE.search(preamble)
        if route:
            path = _STRING_RE.search(source.text, method.preamble_start + route.start(), method.body.start)
            routes.append((method, bool(_GUARD.search(preamble)), path.group(0)[1:-1] if path else "", bool(_MUTATES.search(preamble))))
    guarded = sum(route[1] for route in routes)
    if guarded < 2:
        return  # guarding endpoints one by one isn't this controller's convention
    start = _class_start(source.code)
    prefix = re.search(r"@RequestMapping\(\s*(?:value\s*=\s*|path\s*=\s*)?(" + _STRING + ")", _preamble(source.text, start) if start >= 0 else "")
    for method, guard, path, mutates in routes:
        words = "_".join(re.findall(r"[a-z]+", ((prefix.group(1) if prefix else "") + path + " " + method.body.name).lower()))
        admin = bool(re.search(r"(?:^|_)admin", words))
        # Like with like: under an admin path every endpoint is compared, elsewhere only those that change something, since reads are often public.
        peers = [peer for peer in routes if peer[0] is not method and (admin or peer[3])]
        if guard or not (admin or mutates) or (PUBLIC_ROUTE.search(words) and not admin) or not peers or not all(peer[1] for peer in peers):
            continue
        yield ("missing-auth", source.line_of(method.body.head), f"Every other {'endpoint under this admin path' if admin else 'endpoint here that changes data'} "
               f"carries a method-security annotation and {method.body.name} doesn't, so any signed-in user can call it. Add the same guard, or record "
               "why it's open.", {})


# ---------------------------------------------------------------- URLs, paths and archives

_REQUEST_PARAM = re.compile(r"@(?:RequestParam|PathVariable|RequestHeader)\b[^,]*?\b(\w+)\s*(?:,|$)")
_URL_PARAM = re.compile(r"\bString\s+(\w+(?:Url|Uri|URL|URI))\s*(?:,|$)")
_CONFIGURED_URL = re.compile(r"^(?:base|server|service|api|endpoint|host|root|proxy|token|jwks|issuer|metadata|discovery|registry|auth|login|upstream|gateway|default|config)", re.I)
_FETCHES = re.compile(r"\.(?:getForObject|getForEntity|postForObject|postForEntity|exchange)\(\s*(\w+)|\.uri\(\s*(?:URI\.create\(\s*)?(\w+)|\bHttpRequest\.newBuilder\(\s*(?:URI\.create\(\s*)?(\w+)"
                      r"|\bnew\s+URL\(\s*(\w+)\s*\)\s*\.open(?:Connection|Stream)\(|(?<![\w.])(\w+)\.open(?:Connection|Stream)\(\)|\bJsoup\.connect\(\s*(\w+)|\bnew\s+Http(?:Get|Post|Head)\(\s*(\w+)")
_HOST_CHECK = re.compile(r"\.getHost\(\)|\bInetAddress\b|is(?:SiteLocal|Loopback|AnyLocal|LinkLocal)Address|[Aa]llow(?:ed)?(?:Hosts?|List|Domains?)|ALLOWED_|[Ww]hitelist|isAllowed\w*\(")


def _ssrf(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    if _HOST_CHECK.search(source.code):
        return
    for method in methods:
        params = re.sub(r"\s+", " ", method.body.params)
        tainted = {match.group(1) for match in _REQUEST_PARAM.finditer(params)}
        tainted |= {match.group(1) for match in _URL_PARAM.finditer(params) if not _CONFIGURED_URL.match(match.group(1))}
        if not tainted or method.body.name[:1].isupper():
            continue  # a constructor takes configuration
        for match in re.finditer(r"(?<![\w.])(\w+)\s*=(?!=)\s*([^;]{1,300});", method.code):
            if len(tainted) < 40 and set(re.findall(r"\w+", match.group(2))) & tainted:
                tainted.add(match.group(1))
        for match in _FETCHES.finditer(method.code):
            name = next(group for group in match.groups() if group)
            if name in tainted:
                yield ("ssrf", method.line(match.start()), f"This fetches {name}, a URL the caller chose, with no check of scheme, host or address, so it "
                       "can be pointed at the cloud metadata service or internal hosts. Allow-list hosts, and refuse private addresses after resolving.", {})
                break


_RESOLVED = re.compile(r"(?<![\w.])(?:(?:final\s+)?(?:Path|var|val)\s+)?(\w+)\s*=\s*(?:[\w.]{1,80}\.resolve\(|Paths\.get\(|Path\.of\()[^;\n]{1,200}?\)\s*;")
_ABSOLUTE_PREFIX = re.compile(r"\.getAbsolutePath\(\)\s*\.startsWith\(|\.getAbsoluteFile\(\)\s*\.toPath\(\)\s*\.startsWith\(")
_ARCHIVE = re.compile(r"\b(?:ZipEntry|ZipFile|ZipInputStream|JarEntry|JarFile|TarArchiveEntry|ArchiveEntry|ZipArchiveEntry)\b")
_ENTRY_PATH = re.compile(r"(?:\bnew\s+File\(\s*[\w.()]+\s*,|\.resolve\(|\bPaths\.get\(\s*[\w.()]+\s*,|\bPath\.of\(\s*[\w.()]+\s*,)\s*(\w+)\.getName\(\)")
_CONTAINED = re.compile(r"\.normalize\(\)[\s\S]{0,400}?\.startsWith\(|\bgetCanonical(?:Path|File)\(\)[\s\S]{0,400}?\.startsWith\(|\.toRealPath\([\s\S]{0,400}?\.startsWith\(")


def _paths(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    archive = bool(_ARCHIVE.search(source.code))
    for method in methods:
        for match in _RESOLVED.finditer(method.code):
            if not method.budget.spend(len(method.code) - match.end()):
                return
            name = re.escape(match.group(1))
            check = re.compile(rf"(?<![\w.]){name}\s*\.\s*startsWith\(").search(method.code, match.end())
            normalized = check and re.compile(rf"(?<![\w.]){name}\s*=\s*{name}\s*\.\s*(?:normalize|toRealPath|toAbsolutePath\(\)\s*\.\s*normalize)\(|(?<![\w.]){name}\s*\.\s*(?:normalize|toRealPath)\(").search(
                method.code, match.end(), check.start())
            if check and not normalized and ".normalize()" not in match.group(0) and "toRealPath" not in match.group(0):
                yield ("weak-path-check", method.line(check.start()), f"{match.group(1)} is checked with startsWith before it's normalized, "
                       "and Path.startsWith compares raw name elements, so root/../../etc/passwd passes. Call normalize() (or toRealPath()) on the "
                       "resolved path before the check.", {})
        for match in _ABSOLUTE_PREFIX.finditer(method.code):
            yield ("weak-path-check", method.line(match.start()), "getAbsolutePath keeps .. segments, so this prefix check passes a path that "
                   "climbs out. Compare canonical paths, or normalized Paths.", {})
        if archive:
            for match in _ENTRY_PATH.finditer(method.code):
                if not _CONTAINED.search(method.code):
                    yield ("unsafe-extract", method.line(match.start()), f"This builds an output path from {match.group(1)}.getName(), so an entry named "
                           "../../x writes outside the target folder (zip slip). Normalize the path and check it starts with the target.", {})
                    break


_SIGNED_TIMESTAMP = re.compile(r"""(?:getHeader\(|@RequestHeader\()\s*(?:(?:value|name)\s*=\s*)?"[\w-]*[Tt]imestamp[\w-]*\"""")
_CLOCK = re.compile(r"\bInstant\.now\(|\bSystem\.currentTimeMillis\(|\bclock\.|\bClock\b|\bDuration\.between\(|\bChronoUnit\.|\bOffsetDateTime\.now\(|\bZonedDateTime\.now\(")
_ARCHIVE_LOOP = re.compile(r"\.getNextEntry\(\)|\.getNextTarEntry\(\)|\.entries\(\)")
_COPIES = re.compile(r"\.transferTo\(|\bFiles\.copy\(|\bIOUtils\.copy\w*\(|\bStreamUtils\.copy\(|\.write\(")
_SIZE_LIMIT = re.compile(r"\.getSize\(\)|\.getCompressedSize\(\)|\b[A-Z_]{0,40}MAX[A-Z_]{0,40}\b|\b[a-z]\w{0,40}?[Mm]ax\w{0,40}\b|\bmax[A-Z]\w{0,40}|[Ll]imit|\bBoundedInputStream\b|\bLimitInputStream\b|\bBoundedReader\b")


def _webhooks_and_archives(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    if "Mac.getInstance(" in source.code and not _CLOCK.search(source.code):
        match = _SIGNED_TIMESTAMP.search(source.text)
        if match and source.code[match.start()] == source.text[match.start()]:
            yield ("webhook-unverified", source.line_of(match.start()), "The request's signed timestamp is read but never compared with the clock, so a "
                   "captured request replays forever with a valid signature. Reject timestamps more than a few minutes from now.", {})
    if not _ARCHIVE.search(source.code):
        return
    for method in methods:
        loop = _ARCHIVE_LOOP.search(method.code)
        if loop and _COPIES.search(method.code, loop.end()) and not _SIZE_LIMIT.search(method.code):
            yield ("unbounded-upload", method.line(loop.start()), "Entries are extracted with no limit on their count, each one's size or the total, so a "
                   "small zip bomb fills the disk. Count entries and bytes as you copy, and stop past fixed limits.", {})


# ---------------------------------------------------------------- randomness

_RANDOM_BOUND = re.compile(r"(?<![\w.])(?:java\.util\.)?Random\s+(\w+)\s*=\s*(?:new\s+)?(?:java\.util\.)?Random\(|\b(?:val|var)\s+(\w+)\s*=\s*(?:java\.util\.)?Random\(")
_GENERATOR = re.compile(r"(?:generate|new|create|make|random)(?:Token|Secret|Password|Otp|OTP|Code|Pin|Salt|Nonce|ApiKey|Key|SessionId)\w*$")


def _insecure_random(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    names = sorted({name for match in _RANDOM_BOUND.finditer(source.code) for name in match.groups() if name})[:50]
    calls = r"\bMath\.random\(\)|\bThreadLocalRandom\.current\(\)\s*\.\s*next\w*\(|\bRandomStringUtils\.random\w*\(|\bnew\s+Random\([^()]*\)\s*\.\s*next\w*\(|\bkotlin\.random\.Random\.\w+\("
    if names:
        calls += rf"|(?<![\w.])(?:{'|'.join(map(re.escape, names))})\s*\.\s*(?:next\w*|ints|longs)\("
    random_call = re.compile(calls)
    reported = set()
    for match in re.finditer(r"(?<![\w.])(\w+)\s*=(?!=)\s*([^;\n]{1,300})", source.code):
        line = source.line_of(match.start())
        if braced.secret_named(match.group(1)) and random_call.search(match.group(2)) and line not in reported:
            reported.add(line)
            yield ("insecure-random", line, f"{match.group(1)} comes from a predictable generator: java.util.Random's next values follow from a few "
                   "outputs. Use SecureRandom for anything that grants access.", {})
    for method in methods:
        if _GENERATOR.match(method.body.name):
            found = random_call.search(method.code)
            if found and method.line(found.start()) not in reported:
                yield ("insecure-random", method.line(found.start()), f"{method.body.name} draws from a predictable generator. Use SecureRandom.", {})


# ---------------------------------------------------------------- data: transactions, races, retries

_TRANSACTIONAL = re.compile(r"@Transactional\b|\bTransactionTemplate\b|\btransactionTemplate\b|\bPlatformTransactionManager\b|\.getTransaction\(|\bbeginTransaction\(|\.begin\(\)|\bwithTransaction\b|\btransaction\s*\{")
_STORE_TYPE = re.compile(r"\w*(?:Repository|Repo|Dao|DAO|Mapper|JdbcTemplate|EntityManager|Session|MongoTemplate)$")
_WRITE_CALL = re.compile(r"(?<![\w.])(?:this\.)?(\w+)\s*\.\s*(save|saveAndFlush|saveAll|delete|deleteById|deleteAll|persist|merge|remove|insert|update|batchUpdate|updateFirst|upsert)\s*\(")


def _store_writes(method: _Method, types: dict[str, str]) -> list[re.Match]:
    return [match for match in _WRITE_CALL.finditer(method.code) if _STORE_TYPE.match(types.get(match.group(1), ""))]


def _without_transaction(source: Source, methods: list[_Method], types: dict[str, str]) -> Iterator[tuple]:
    if _TRANSACTIONAL.search(_class_preamble(source.code)) or re.search(r"\binterface\s+\w+", source.code):
        return
    for method in methods:
        writes = _store_writes(method, types)
        if len(writes) >= 2 and len({write.group(1) for write in writes}) >= 2 and not _TRANSACTIONAL.search(method.preamble + method.code):
            yield ("multi-write-no-transaction", method.line(writes[1].start()), f"{method.body.name} saves through {len(writes)} repository calls with no "
                   "transaction, so each commits on its own and a failure part way leaves the first ones applied. Annotate it @Transactional, or say why "
                   "half done is safe.", {})


_LOCKING = re.compile(r"@Lock\b|\bLockModeType\b|PESSIMISTIC|OptimisticLock|@Version\b|FOR\s+UPDATE|ForUpdate|\bWithLock\b|\bversion\b\s*=", re.I)
_SETTER_FROM_GETTER = re.compile(r"(?<![\w.])(\w+)\.set(\w+)\(\s*\1\.get\2\(\)\s*(?:\.\s*(?:add|subtract|plus|minus|multiply|negate)\(|[-+*/])"
                                 r"|(?<![\w.])(\w+)\.(\w+)\s*(?:[-+]=|=\s*\3\.\4\s*[-+])")
_LOADED = re.compile(r"(?<![\w.])(\w+)\s*=\s*[\w.]{1,80}\.(?:findById|getById|getReferenceById|getOne|findBy\w{0,60}|findOne\w{0,60}|find|load|get)\(")
_SAVED = re.compile(r"\.(?:save|saveAndFlush|merge|update)\(\s*(\w+)\s*\)")


def _lost_update(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    if _LOCKING.search(source.code):
        return
    for method in methods:
        loaded: dict[str, int] = {}
        for found in _LOADED.finditer(method.code):
            loaded.setdefault(found.group(1), found.start())
        saved: dict[str, int] = {}
        for found in _SAVED.finditer(method.code):
            saved[found.group(1)] = found.start()  # the last save of each
        transactional = bool(_TRANSACTIONAL.search(method.preamble))
        for change in _SETTER_FROM_GETTER.finditer(method.code):
            owner = change.group(1) or change.group(3)
            field = change.group(2) or change.group(4)
            if loaded.get(owner, len(method.code)) < change.start() and (saved.get(owner, -1) > change.end() or transactional):
                yield ("lost-update", method.line(change.start()), f"{owner}.{field[:1].lower() + field[1:]} is loaded, changed in memory and saved with no lock or "
                       "version, so two requests at once both start from the old value and one change is lost. Add @Version to the entity, lock the row "
                       "(@Lock(PESSIMISTIC_WRITE)), or update it in one statement.", {})
                break


_EXISTS_CHECK = re.compile(r"\bif\s*\(\s*!?\s*(?:[\w.]{1,80}\.(?:existsBy\w+|existsById)\([^()]*\)|[\w.]{1,80}\.(?:findBy\w+|findOneBy\w+)\([^()]*\)\s*\.\s*(?:isPresent|isEmpty)\(\)"
                           r"|[\w.]{1,80}\.countBy\w+\([^()]*\)\s*(?:>|!=|==)\s*0)")
_INSERTS = re.compile(r"\.(?:save|saveAndFlush|insert|persist)\(")
_HANDLES_DUPLICATE = re.compile(r"DataIntegrityViolationException|DuplicateKeyException|ConstraintViolationException|SQLIntegrityConstraintViolationException|ON\s+CONFLICT|ON\s+DUPLICATE", re.I)


def _check_then_insert(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    if _HANDLES_DUPLICATE.search(source.text):
        return
    for method in methods:
        check = _EXISTS_CHECK.search(method.code)
        insert = _INSERTS.search(method.code, check.end()) if check else None
        if insert:
            yield ("check-then-insert", method.line(insert.start()), "This checks the row doesn't exist and then saves it, so two requests at once both "
                   "pass the check and both insert. Back it with a unique constraint and handle DataIntegrityViolationException, or use an upsert.", {})


_RETRY_ANNOTATION = re.compile(r"@(?:Retry|Retryable)\b")
_HAND_RETRY = re.compile(r"\bfor\s*\(\s*(?:int|var)\s+(\w+)\s*=\s*\d+\s*;\s*\w+\s*<=?\s*[\w.]+\s*;\s*\w+\s*\+\+\s*\)\s*\{|\bwhile\s*\(\s*[^()\n]{0,80}\b(?i:\w*(?:attempt|retr|tries)\w*)[^()\n]{0,80}\)\s*\{")
_RETRY_WORD = re.compile(r"retr|attempt|tries", re.I)
_WAITS = re.compile(r"\bThread\.sleep\(|\bTimeUnit\.\w+\.sleep\(|[Bb]ackoff|\bdelay\(")
_POST = re.compile(r"\.POST\(|\bHttpMethod\.POST\b|\.postFor\w+\(|\.post\(\)")
_EFFECT_VERB = re.compile(r"(?:create|send|charge|refund|pay|transfer|publish|post|submit|place|issue|capture|withdraw|deposit|provision|launch)\w*$", re.I)
_REMOTE_TYPE = re.compile(r"\w*(?:Client|Api|API|Gateway|Provider|Sender|Publisher|Producer|RestTemplate|KafkaTemplate|RabbitTemplate|WebClient|Psp|PSP)$")
_IDEMPOTENT = re.compile(r"[Ii]dempoten|[Dd]edup|Idempotency-Key")


def _effect(code: str, types: dict[str, str]) -> str | None:
    post = _POST.search(code)
    if post:
        return "a POST"
    for match in re.finditer(r"(?<![\w.])(?:this\.)?(\w+)\s*\.\s*(\w+)\s*\(", code):
        if _REMOTE_TYPE.match(types.get(match.group(1), "")) and _EFFECT_VERB.match(match.group(2)):
            return f"{match.group(1)}.{match.group(2)}"
    return None


def _retried_effects(source: Source, methods: list[_Method], types: dict[str, str]) -> Iterator[tuple]:
    if _IDEMPOTENT.search(source.text):
        return
    for method in methods:
        effect = _effect(method.code, types)
        if not effect:
            continue
        if _RETRY_ANNOTATION.search(method.preamble):
            yield ("retry-not-idempotent", source.line_of(method.body.head), f"{method.body.name} is retried, and it makes {effect} with no idempotency key, "
                   "so a timeout after the far side acted repeats it. Send a key the far side deduplicates on, or retry only errors that prove nothing happened.", {})
            continue
        for loop in _HAND_RETRY.finditer(method.code):
            start = method.offset + loop.end()
            closing = method.pairs.get(start - 1, -1)
            if closing < 0 or not method.budget.spend(closing - start):
                continue
            named = _RETRY_WORD.search(loop.group(0) + method.code[max(0, loop.start() - 300):loop.start()])
            if named and re.compile(r"\bcatch\b").search(source.code, start, closing) and _WAITS.search(source.code, start, closing):
                yield ("retry-not-idempotent", method.line(loop.start()), f"This loop retries {effect} after a failure with no idempotency key, so a timeout "
                       "after the far side acted repeats it. Send a key the far side deduplicates on, or retry only errors that prove nothing happened.", {})
                break


# ---------------------------------------------------------------- acknowledgements, locks, files and shared state

_ACK = re.compile(r"(?<![\w.])\w+\s*\.\s*(?:acknowledge|commitSync|commitAsync|basicAck|deleteMessage)\(")
_HANDOFF = re.compile(r"\.(?:submit|execute)\(|\bCompletableFuture\.(?:runAsync|supplyAsync)\(|\b(?:launch|async)\s*\{")
_NOT_WORK = re.compile(r"(?:log|logger|LOG|LOGGER|metrics|meter|span|tracer|ack|acknowledgment|acknowledgement|consumer|channel|record|message|msg)$")


def _ack_first(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    for method in methods:
        ack = _ACK.search(method.code)
        if not ack:
            continue
        before = [match for match in re.finditer(r"(?<![\w.])(\w+)\s*\.\s*\w+\s*\(", method.code[:ack.start()]) if not _NOT_WORK.match(match.group(1))]
        after = [match for match in re.finditer(r"(?<![\w.])(\w+)\s*\.\s*\w+\s*\(", method.code[ack.end():]) if not _NOT_WORK.match(match.group(1))]
        handoff = _HANDOFF.search(method.code, ack.end())
        if handoff or (not before and after and "catch" not in method.code[:ack.start()]):
            yield ("checkpoint-before-effect", method.line(ack.start()), "The message is acknowledged before the work it carries is done, so a crash or an "
                   "error afterwards loses it for good. Acknowledge after the work commits, and do the work on the listener thread or track it to completion.", {})


_LEASED_LOCK = re.compile(r"\.lock\(\s*[\w.]+\s*,\s*(?:TimeUnit\.)?[A-Z]+\s*\)|\.tryLock\(\s*[\w.]+\s*,\s*[\w.]+\s*,\s*(?:TimeUnit\.)?[A-Z]+\s*\)")
_REDIS_LOCK_DELETE = re.compile(r"\.del\(\s*(\w*(?i:lock)\w*)\s*\)")


def _locks(source: Source) -> Iterator[tuple]:
    if re.search(r"\bRLock\b|\bRedisson\w*\b|\bredisson\b", source.code):
        for match in _LEASED_LOCK.finditer(source.code):
            yield ("lock-without-fencing", source.line_of(match.start()), "This lock has a fixed lease, so if the work outlives it another node takes the "
                   "lock while this one is still writing. Leave the lease to the watchdog and fence the writes with a token the store checks.", {})
    if re.search(r"\bsetnx\(|\bsetNX\(|\bnx\(\)|SetParams", source.code, re.I):
        for match in _REDIS_LOCK_DELETE.finditer(source.code):
            yield ("lock-without-fencing", source.line_of(match.start()), "This deletes the lock key without checking it still holds the value it set, so "
                   "after the lease expires it removes another holder's lock. Delete with a compare-and-delete script.", {})


_IN_PLACE = re.compile(r"\bFiles\.(?:write|writeString|newBufferedWriter|newOutputStream)\([^;]{0,400}?\bTRUNCATE_EXISTING\b")


def _in_place_writes(source: Source) -> Iterator[tuple]:
    if re.search(r"\bATOMIC_MOVE\b|\bFiles\.move\(|\bcreateTempFile\(", source.code):
        return
    for match in _IN_PLACE.finditer(source.code):
        yield ("nonatomic-state-write", source.line_of(match.start()), "This truncates the file and rewrites it in place, so a crash part way leaves a "
               "partial file where the last good one was. Write a temporary file beside it and Files.move it over with ATOMIC_MOVE.", _MEDIUM)


# Anchored on the type: an optional prefix before `\s*` would retry across every blank run the code view leaves for comments.
_UNSAFE_COLLECTION = re.compile(r"\b(?:Map|HashMap|List|ArrayList|Set|HashSet|LinkedHashMap|TreeMap|LinkedList|Deque|ArrayDeque|Queue)"
                                r"<[^;=\n]{0,200}>[ \t]+(\w+)[ \t]*=[ \t]*new[ \t]+(?:HashMap|ArrayList|HashSet|LinkedHashMap|TreeMap|LinkedList|ArrayDeque)\b")
_COUNTER = re.compile(r"(?:private|protected|public)\s+(?:static\s+)?(?:volatile\s+)?(?:long|int|double)\s+(\w+)\s*(?:=\s*[\d.]+[lL]?\s*)?;")
_COLLECTION_CHANGE = re.compile(r"(?<![\w.])(?:this\.)?(\w+)\s*\.\s*(?:put|putAll|remove|add|addAll|clear|computeIfAbsent|compute|merge|putIfAbsent|removeIf|set|poll|push|offer)\(")
_COUNTER_CHANGE = re.compile(r"(?<![\w.])(?:this\.)?(\w+)\s*(?:\+\+|--|[-+]=)|(?:\+\+|--)\s*(?:this\.)?(\w+)\b")
_SYNCHRONIZED = re.compile(r"\bsynchronized\b|\bReentrant\w*Lock\b|\.lock\(\)|\bCollections\.synchronized\w+\(|@Synchronized\b|\bStampedLock\b|\bReadWriteLock\b|\bMutex\b")


def _shared_state(source: Source, methods: list[_Method]) -> Iterator[tuple]:
    code = source.code
    if not _SPRING_BEAN.search(_class_preamble(code)) or _SYNCHRONIZED.search(code) or re.search(r"@(?:RequestScope|SessionScope|Scope\(\s*\"prototype)", source.text):
        return
    class_name = re.search(r"\bclass\s+(\w+)", code)
    request_methods = [method for method in methods if not (class_name and method.body.name == class_name.group(1)) and "@PostConstruct" not in method.preamble]
    bodies = [method.body for method in methods]
    starts = [body.start for body in bodies]
    for pattern, changes in ((_UNSAFE_COLLECTION, _COLLECTION_CHANGE), (_COUNTER, _COUNTER_CHANGE)):
        changed = {name for method in request_methods for found in changes.finditer(method.code) for name in found.groups() if name}
        for match in pattern.finditer(code):
            if braced.enclosing(bodies, match.start(), starts):
                continue  # a local, which only this call sees
            if match.group(1) in changed:
                yield ("unsynchronized-state", source.line_of(match.start()), f"{match.group(1)} lives in a singleton bean and request threads change it "
                       "with no synchronization, so concurrent requests corrupt it or lose updates. Use ConcurrentHashMap, LongAdder or AtomicLong, or a lock.", {})
                return


_ASSERT = re.compile(r"^[ \t]*assert[ \t(][^;\n]{1,300}", re.M)


def _asserts(source: Source) -> Iterator[tuple]:
    if not _SPRING_BEAN.search(_class_preamble(source.code)):
        return
    for match in _ASSERT.finditer(source.code):
        yield ("assert-validation", source.line_of(match.start()), "Java runs assert only with -ea, which production JVMs leave off, so this check "
               "never runs there. Throw an exception for anything a caller can get wrong.", _MEDIUM)


def findings(source: Source, is_test: bool) -> Iterable[tuple]:
    """(rule, line, message, overrides) for one Java or Kotlin file."""
    if is_test:
        return []
    pairs = braced.pairs(source.code)
    budget = braced.Budget(source.code)
    methods = [_Method(source, body, pairs, budget) for body in braced.functions(source, pairs)]
    types = _field_types(source.code)
    found: list[tuple] = []
    for check in (lambda: _sql(source, methods), lambda: _patterns(source), lambda: _spring_security(source), lambda: _fail_open(source, methods),
                  lambda: _missing_auth(source, methods), lambda: _ssrf(source, methods), lambda: _paths(source, methods),
                  lambda: _insecure_random(source, methods), lambda: _without_transaction(source, methods, types), lambda: _lost_update(source, methods),
                  lambda: _check_then_insert(source, methods), lambda: _retried_effects(source, methods, types), lambda: _ack_first(source, methods),
                  lambda: _locks(source), lambda: _in_place_writes(source), lambda: _shared_state(source, methods), lambda: _asserts(source),
                  lambda: _webhooks_and_archives(source, methods)):
        found += check()
    return braced.one_per_line(found)
