"""Go checks that need more than one pattern: SQL and shell commands built from values, archive paths, request-chosen URLs, CORS origin
checks, fail-open authorization, predictable secrets, and the data rows: writes outside a transaction, read-modify-write, check-then-insert,
retried effects, checkpoints and locks.

They report under the ids the other languages use where the failure is the same. None is high severity with high confidence unless the
request's own value reaches the sink on that line, so none sends an agent back at Stop on a guess (DESIGN.md no-new-send-backs).
"""

from __future__ import annotations

import bisect
import re
from typing import Iterable, Iterator

from . import rules_braced as braced
from .py_helpers import PLACEHOLDER_NAME, _has_sql
from .source import Source

_MEDIUM = {"confidence": "medium"}
_STRING = r'"(?:[^"\\\n]|\\.)*"|`[^`]*`'
_STRING_RE = re.compile(_STRING)

# ---------------------------------------------------------------- reading values

_REQUEST_READ = re.compile(r"\b(?:r|req|request)\.(?:FormValue|PostFormValue|PathValue)\(|\b(?:r|req|request)\.URL\.Query\(\)|\b(?:r|req|request)\.Header\.Get\("
                           r"|\bc\.(?:Query|DefaultQuery|Param|PostForm|DefaultPostForm|QueryParam|FormValue|Params|GetHeader)\(|\bmux\.Vars\(|\bchi\.URLParam\(")
_DECODED_FROM_REQUEST = re.compile(r"(?:json\.NewDecoder\([^()\n]{0,80}\.Body[^()\n]{0,40}(?:\([^()\n]{0,60}\))?[^()\n]{0,20}\)\.Decode"
                                   r"|\bc\.(?:ShouldBind\w*|Bind\w*)|\bjson\.Unmarshal\([^,\n]{1,80},)\(\s*&\s*(\w+)\s*\)")
_CONSTS = re.compile(r"^const[ \t]+(\w+)[^\n=]{0,80}=|^const[ \t]*(\()", re.M)
_CONST_IN_BLOCK = re.compile(r"^[ \t]*(\w+)\b", re.M)
# Calls whose result can't carry text from outside: numbers, quoted identifiers, and a literal repeated, as strings.Repeat("?,", n).
_SAFE_CALL = re.compile(r"^(?:strconv\.\w+|len|cap|int\w*|uint\w*|float\w*|pq\.QuoteIdentifier|pgx\.Identifier\{.*\}\.Sanitize|\w*[Qq]uote[Ii]dent\w*|time\.\w+"
                        r"|strings\.Repeat(?=\(\s*[\"`]))\s*\(")
_SQL_VERB = re.compile(r"%[-+# 0]*\d*(?:\.\d+)?([a-zA-Z%])")
_FUNCTION_RECEIVER = re.compile(r"func[ \t]+\([ \t]*(\w+)")


def _constants(code: str, pairs: dict[int, int]) -> set[str]:
    names = set()
    for match in _CONSTS.finditer(code):
        if match.group(1):
            names.add(match.group(1))
        else:
            closing = pairs.get(match.start(2), -1)
            if closing > 0:
                names.update(name.group(1) for name in _CONST_IN_BLOCK.finditer(code, match.end(2), closing))
    return names


class _Function:
    """One function's text and the assignments in it, read once."""

    def __init__(self, source: Source, body: braced.Body, pairs: dict[int, int], budget: braced.Budget) -> None:
        self.source, self.body, self.pairs, self.budget = source, body, pairs, budget
        self.code = source.code[body.start:body.end]
        self.offset = body.start
        receiver = _FUNCTION_RECEIVER.match(source.code, body.head)
        self.receiver = receiver.group(1) if receiver else None
        self._seen: dict[tuple[str, int], list[tuple[str, int, int]]] = {}

    def assignments(self, name: str, before: int) -> list[tuple[str, int, int]]:
        """(kind, start, end) of each value given to `name` before this offset. Kinds: `set` for := and =, `add` for += and
        `name = append(name, v)`, `write` for name.WriteString(v), `fprintf` for fmt.Fprintf(&name, ...) and `index` for name[i] = v."""
        if (name, before) in self._seen:
            return self._seen[(name, before)]
        spans: list[tuple[str, int, int]] = []
        self._seen[(name, before)] = spans  # filled below, and what a recursive look at the same name sees meanwhile
        if not self.budget.spend(before - self.offset):
            return spans
        escaped = re.escape(name)
        pattern = re.compile(rf"(?<![\w.]){escaped}(\[[^\]\n]{{0,80}}\])?\s*(:=|\+=|=(?!=))|(?<![\w.]){escaped}\.(?:WriteString|WriteByte|WriteRune|Write)\(|fmt\.Fprint\w*\(\s*&{escaped}\s*,")
        code = self.source.code
        for match in pattern.finditer(code, self.offset, before):
            if match.group(0).endswith("("):
                closing = self.pairs.get(match.end() - 1, -1)
                if closing > 0:
                    spans.append(("write", match.end(), min(closing, before)))
                continue
            if match.group(0).startswith("fmt."):
                opening = code.rfind("(", match.start(), match.end())
                spans.append(("fprintf", opening, min(self.pairs.get(opening, opening), before)))
                continue
            end = code.find("\n", match.end())
            end = before if end < 0 else min(end, before)
            for position in range(match.end(), min(end, match.end() + 400)):  # a value carries on while its brackets stay open
                if code[position] in "([{":
                    end = max(end, min(self.pairs.get(position, end), before, match.end() + 3000))
            kind = "index" if match.group(1) else "add" if match.group(2) == "+=" else "set"
            appended = re.match(rf"\s*append\(\s*{escaped}\s*,", code[match.end():end])
            if appended:
                kind = "add"
            spans.append((kind, match.end() + (appended.end() if appended else 0), end))
            if len(spans) > 200:
                break  # enough to judge by, and a bound on what one name costs
        return spans


_DEPTH = 3
_STRING_SLICE = re.compile(r"\[\]string\{[\s,\"`]*\}")  # `[]string{"1=1", "a = ?"}`, whose strings the code view blanks


class _Sql:
    """Is this expression SQL text with a runtime value spliced in? Follows a name back to what built it, within the function. What
    can't be seen, such as a list filled in another function, counts as safe, so a guess never blocks gate."""

    def __init__(self, source: Source, function: _Function, constants: set[str], package_vars: set[str]) -> None:
        self.source, self.function, self.constants, self.package_vars = source, function, constants, package_vars
        self.params = set(re.findall(r"\w+", function.body.params))
        self._checked: dict[tuple[str, int], bool] = {}

    def _value_safe(self, start: int, end: int, before: int, depth: int) -> bool:
        """One value given to a name or put in a list: literal text, a safe operand, or something built with nothing unsafe spliced in."""
        code = self.source.code
        values = braced.parts(code, start, end, ",") or [(start, end)]  # append(list, a, b) puts in several
        for value_start, value_end in values:
            value = code[value_start:value_end].strip()
            while value.endswith(")") and value.count(")") > value.count("("):
                value = value[:-1].rstrip()
            if not value or value.startswith("make(") or _STRING_SLICE.fullmatch(value):
                continue
            if "fmt.Sprintf(" in value or "+" in value:
                if self.built(value_start, value_start + len(value), depth + 1)[1]:
                    return False
            elif not self.safe(value, before, depth + 1):
                return False
        return True

    def _list_safe(self, name: str, before: int, depth: int) -> bool:
        """Every value put in the list is safe: `conds := []string{"1=1"}`, `append(conds, "name = ?")`, `marks[i] = fmt.Sprintf("$%d", i)`."""
        spans = self.function.assignments(name, before)
        return all(self._value_safe(start, end, before, depth) for kind, start, end in spans if kind != "fprintf")

    def _allowlisted(self, name: str, before: int) -> bool:
        """Checked against a fixed set before use: a map lookup in a condition, a switch, slices.Contains, or an allow or valid helper."""
        if (name, before) in self._checked:
            return self._checked[(name, before)]
        self._checked[(name, before)] = False
        if not self.function.budget.spend(before - self.function.offset):
            return False
        escaped = re.escape(name)
        checked = re.compile(rf"\bif\b[^{{\n]{{0,160}}[\w.]+\[\s*{escaped}\s*\]|\b\w+\s*,\s*\w+\s*:?=\s*[\w.]+\[\s*{escaped}\s*\]|\bswitch\s+{escaped}\s*\{{"
                             rf"|\bslices\.Contains\(\s*[\w.]+\s*,\s*{escaped}\s*\)|\b\w*(?:[Aa]llow|[Vv]alid|[Ss]ortable|[Ww]hitelist|[Pp]ermitted)\w*\(\s*{escaped}\s*\)")
        self._checked[(name, before)] = bool(checked.search(self.source.code, self.function.offset, before))
        return self._checked[(name, before)]

    def safe(self, operand: str, before: int, depth: int) -> bool:
        operand = operand.strip().lstrip("*&").strip()
        if not operand or operand[0] in "\"`'" or operand[0].isdigit() or operand in self.constants or operand.isupper() or _SAFE_CALL.match(operand):
            return True
        if depth >= _DEPTH:
            return False
        joined = re.fullmatch(r"strings\.Join\(\s*(\w+)\s*,[^()]*\)", operand)
        if joined:
            return self._list_safe(joined.group(1), before, depth)
        indexed = re.fullmatch(r"(\w+)\[[^\]]*\]", operand)
        if indexed:
            return indexed.group(1) in self.package_vars  # a lookup in a fixed table, as `columns[sort]`
        if not re.fullmatch(r"\w+", operand):
            return False
        if self._allowlisted(operand, before):
            return True
        spans = [span for span in self.function.assignments(operand, before) if span[0] != "index"]
        if operand in self.params or not spans:
            return bool(PLACEHOLDER_NAME.fullmatch(operand)) and self._list_safe(operand, before, depth)
        return all(self._value_safe(start, end, before, depth) for kind, start, end in spans if kind != "fprintf")

    def _formatted(self, opening: int, before: int, depth: int, skip: int = 0) -> tuple[bool, bool]:
        """A Sprintf-style call: its format's SQL, and whether a %s, %v or %q takes a value that isn't safe."""
        code, text = self.source.code, self.source.text
        args = braced.arguments(code, opening, self.function.pairs)[skip:]
        if not args:
            return False, False
        start, end = braced.strip(code, args[0])
        form = braced.literal_text(text, start, end, _STRING_RE)
        if not form and depth < _DEPTH and re.fullmatch(r"\w+", code[start:end]):
            form = " ".join(braced.literal_text(text, a, b, _STRING_RE) for _, a, b in self.function.assignments(code[start:end], before))
        verbs = [verb for verb in _SQL_VERB.findall(form) if verb != "%"]
        spliced = any(verb in "svqxX" and not self.safe(code[a:b], before, depth) for verb, (a, b) in zip(verbs, args[1:]))
        return _has_sql(form), spliced

    def built(self, start: int, end: int, depth: int = 0) -> tuple[bool, bool]:
        """(has SQL text, has a runtime value spliced in) for the expression at [start, end)."""
        code, text = self.source.code, self.source.text
        expression = code[start:end].strip()
        literals = braced.literal_text(text, start, end, _STRING_RE)
        sql, spliced = _has_sql(literals), False
        for call in re.finditer(r"\bfmt\.Sprintf\(", code[start:end]):
            found_sql, found_spliced = self._formatted(start + call.end() - 1, start, depth)
            sql, spliced = sql or found_sql, spliced or found_spliced
        if literals and "+" in code[start:end]:
            spliced = spliced or any(not self.safe(code[a:b], start, depth) for a, b in braced.parts(code, start, end, "+") if "fmt.Sprintf(" not in code[a:b])
        if depth < _DEPTH and re.fullmatch(r"\w+(?:\.String\(\))?", expression):
            for kind, value_start, value_end in self.function.assignments(expression.split(".")[0], start):
                if kind == "index":
                    continue
                if kind == "fprintf":
                    found_sql, found_spliced = self._formatted(value_start, start, depth + 1, skip=1)
                else:
                    found_sql, found_spliced = self.built(value_start, value_end, depth + 1)
                    value = code[value_start:value_end].strip()
                    if kind in ("add", "write") and not found_spliced and value and not _STRING_RE.fullmatch(text[value_start:value_end].strip()):
                        found_spliced = "fmt.Sprintf(" not in value and "+" not in value and not self._value_safe(value_start, value_end, start, depth)
                sql, spliced = sql or found_sql, spliced or found_spliced
        return sql, spliced


_SQL_CALL = re.compile(r"\.(Query|QueryRow|QueryContext|QueryRowContext|Exec|ExecContext|Queryx|QueryRowx|QueryxContext|QueryRowxContext|Select|SelectContext"
                       r"|Get|GetContext|MustExec|MustExecContext|NamedExec|NamedExecContext|NamedQuery|NamedQueryContext|Raw|Prepare|PrepareContext|Where|Order)\(")


# What rules_text's sql-injection pattern already reports: a Sprintf or a concatenation written inside the call.
_INLINE_SQL = re.compile(r"""\.(?:Query|QueryRow|Exec)(?:Context)?\((?:\w+,\s*)?(?:fmt\.Sprintf\(|"[^"\n]*"\s*\+)""")


def _sql(source: Source, functions: list[_Function], constants: set[str]) -> Iterator[tuple]:
    package_vars = set(re.findall(r"^var[ \t]+(\w+)[ \t]*=", source.code, re.M))
    code = source.code
    for function in functions:
        reader = _Sql(source, function, constants, package_vars)
        for match in _SQL_CALL.finditer(code, function.offset, function.body.end):
            if _INLINE_SQL.match(source.text, match.start()):
                continue
            if function.budget.left <= 0:
                return
            args = braced.arguments(code, match.end() - 1, function.pairs)
            for position, (start, end) in enumerate(args[:3]):
                start, end = braced.strip(code, (start, end))
                expression = code[start:end]
                if not expression or expression.startswith("&") or expression in ("ctx", "context.Background()"):
                    continue
                sql, spliced = reader.built(start, end)
                if sql and spliced:
                    direct = "fmt.Sprintf(" in expression or "+" in expression
                    on_line = bool(_REQUEST_READ.search(source.text[start:end]))
                    how = "built here" if direct else f"built earlier into {expression.split('.')[0]}"
                    yield ("sql-injection", source.line_of(match.start()), f".{match.group(1)}() runs SQL {how} with a runtime value spliced into the text. "
                           "Pass values as bind arguments ($1 or ?), and check identifiers against a fixed list.", {} if on_line else _MEDIUM)
                    break


# ---------------------------------------------------------------- shell

_SHELL = re.compile(r"""\bexec\.Command(Context)?\(\s*(?:[\w.()]+\s*,\s*)?"(?:/usr)?(?:/bin/)?(?:ba|z|da|k)?sh"\s*,\s*"-\w*c"\s*,\s*""")
_LITERAL_ARGUMENT = re.compile(rf"(?:{_STRING})\s*[,)]")


def _shell(source: Source) -> Iterator[tuple]:
    for match in _SHELL.finditer(source.text):
        if source.code[match.start()] != source.text[match.start()] or _LITERAL_ARGUMENT.match(source.text, match.end()):
            continue  # inside a string or comment, or a fixed command line
        line_end = source.text.find("\n", match.end(), match.end() + 400)
        on_line = bool(_REQUEST_READ.search(source.text, match.end(), line_end if line_end > 0 else match.end() + 400))
        yield ("shell-injection", source.line_of(match.start()), "This runs a command line built at runtime through a shell, so a quote, ; or $( ) in any value "
               "becomes shell syntax. Run the program directly with an argument list, and put -- before values.", {} if on_line else _MEDIUM)


# ---------------------------------------------------------------- paths from archives

_ARCHIVE_READER = re.compile(r"\b(?:zip\.OpenReader|zip\.NewReader|tar\.NewReader)\(|\*(?:zip\.File|tar\.Header)\b")
_ENTRY_JOIN = re.compile(r"\b(?:filepath|path)\.Join\(([^()\n]{0,200}?\b\w+\.(?:Name|FileHeader\.Name)\b(?!\s*\())")
_CONTAINED = re.compile(r"\bfilepath\.Rel\(|\bstrings\.HasPrefix\(|\bfilepath\.IsLocal\(|\bSecureJoin|\bsecurejoin\.|\bstrings\.Contains\([^()\n]{1,80}\.\.|\bIsLocal\(|\bValidPath\(|\bwithin\w*\(|\bsafe\w*\(", re.I)


def _archive_paths(source: Source, bodies: list[braced.Body]) -> Iterator[tuple]:
    if not _ARCHIVE_READER.search(source.code):
        return  # names from somewhere else, or an archive being written
    starts, checked = [body.start for body in bodies], set()
    for match in _ENTRY_JOIN.finditer(source.code):
        body = braced.enclosing(bodies, match.start(), starts)
        if body in checked:
            continue
        checked.add(body)
        scope = source.code[body.start:body.end] if body else source.code
        if not _CONTAINED.search(scope):
            yield ("unsafe-extract", source.line_of(match.start()), "This joins an archive entry's name onto the destination, so an entry named ../../x writes "
                   "outside it (zip slip). Clean the joined path and check filepath.Rel stays inside, or use filepath.IsLocal on the name.", {})


# ---------------------------------------------------------------- admin routes left outside the admin guard

_GROUP = re.compile(r"(?<![\w.])(\w+)\s*:?=\s*(\w+)\.Group\(\s*\"([^\"\n]*)\"([^\n]*)")
_USES = re.compile(r"(?<![\w.])(\w+)\.Use\(([^\n]*)")
_ROUTE = re.compile(r"(?<![\w.])(\w+)\.(?:GET|POST|PUT|PATCH|DELETE|Any|Handle|HandleFunc|Get|Post|Put|Patch|Delete)\(\s*\"([^\"\n]+)\"([^\n]*)")
_ROLE_GUARD = re.compile(r"[Rr]ole|[Aa]dmin|[Pp]ermission|[Aa]uthoriz|[Ss]uperuser|[Ss]taff|[Ss]cope", re.I)


def _admin_routes(source: Source) -> Iterator[tuple]:
    """Routers built in groups: a route whose full path is under /admin, registered where no role guard applies, while the file guards
    another group with one. Authentication alone doesn't make a user an admin."""
    text = source.text
    groups: dict[str, tuple[str, str, bool]] = {}  # name: (parent, prefix, guarded by a role)
    for match in _GROUP.finditer(text):
        groups[match.group(1)] = (match.group(2), match.group(3), bool(_ROLE_GUARD.search(match.group(4))))
    for match in _USES.finditer(text):
        if match.group(1) in groups and _ROLE_GUARD.search(match.group(2)):
            parent, prefix, _ = groups[match.group(1)]
            groups[match.group(1)] = (parent, prefix, True)
    if not any(guarded for _, _, guarded in groups.values()):
        return

    def chain(name: str) -> tuple[str, bool]:
        prefix, guarded, seen = "", False, set()
        while name in groups and name not in seen and len(seen) < 12:
            seen.add(name)
            parent, part, role = groups[name]
            prefix, guarded, name = part + prefix, guarded or role, parent
        return prefix, guarded

    for match in _ROUTE.finditer(text):
        if source.code[match.start()] != text[match.start()]:
            continue
        prefix, guarded = chain(match.group(1))
        path = prefix + match.group(2)
        if re.search(r"(?:^|/)admin(?:/|$|[-_])", path, re.I) and not guarded and not _ROLE_GUARD.search(match.group(3)):
            yield ("missing-auth", source.line_of(match.start()), f"{path} is an admin path, but it's registered on {match.group(1)}, which no role check "
                   "guards, while another group here has one. Register it on the admin group, or add the role check to the route.", {})


# ---------------------------------------------------------------- URLs chosen by the request

_FETCH = re.compile(r"\bhttp\.(?:Get|Head|Post|PostForm)\(|\bhttp\.DefaultClient\.(?:Get|Head|Post|PostForm)\(")
_HOST_CHECK = re.compile(r"\.Hostname\(\)|\.Host\b|\bnet\.(?:LookupIP|LookupHost|ParseIP)\b|\bnetip\.|\bIsPrivate\(|\bIsLoopback\(|[Aa]llow(?:ed)?(?:Hosts?|List|Domains?)|[Ww]hitelist", re.I)


def _tainted_names(function: _Function) -> set[str]:
    code = function.code
    names = {match.group(1) for match in _DECODED_FROM_REQUEST.finditer(code)}
    for match in re.finditer(r"(?<![\w.])(\w+)(?:\s*,\s*\w+)?\s*:?=(?!=)\s*([^\n]{1,300})", code):
        value = match.group(2)
        if len(names) < 40 and (_REQUEST_READ.search(value) or set(re.findall(r"(?<![\w.])\w+", value)) & names):
            names.add(match.group(1))
    return names


def _ssrf(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    for function in functions:
        if _HOST_CHECK.search(function.code):
            continue
        names = None
        for match in _FETCH.finditer(source.code, function.offset, function.body.end):
            args = braced.arguments(source.code, match.end() - 1, function.pairs)
            if not args:
                continue
            start, end = braced.strip(source.code, args[0])
            argument = source.code[start:end]
            names = _tainted_names(function) if names is None else names
            root = re.match(r"\w+", argument)
            if _REQUEST_READ.search(source.text[start:end]) or (root and root.group(0) in names):
                yield ("ssrf", source.line_of(match.start()), "This fetches a URL the request chose, with the default client, which follows redirects and reaches "
                       "any address, including the cloud metadata service and internal hosts. Allow-list hosts, and refuse private addresses at dial time.", {})


# ---------------------------------------------------------------- CORS

_CORS_FILE = re.compile(r"Access-Control-Allow-Origin|AllowOriginFunc|AllowOrigins|AllowedOrigins")
_SUFFIX_CHECK = re.compile(rf"\bstrings\.(HasSuffix|Contains)\(\s*([^,()\n]{{1,80}}(?:\(\))?)\s*,\s*({_STRING}|\w+)\s*\)")
_ANY_ORIGIN_FUNC = re.compile(r"AllowOriginFunc\s*:\s*func\(\s*\w+\s+string\s*\)\s*bool\s*\{\s*return\s+true\s*\}")
_WILDCARD_WITH_CREDENTIALS = re.compile(r"""Allow(?:ed)?Origins\s*:\s*\[\]string\{\s*"\*"\s*\}[^{}]{0,600}AllowCredentials\s*:\s*true|AllowCredentials\s*:\s*true[^{}]{0,600}Allow(?:ed)?Origins\s*:\s*\[\]string\{\s*"\*"\s*\}""")


def _cors(source: Source) -> Iterator[tuple]:
    text = source.text
    if not _CORS_FILE.search(text):
        return
    values = {match.group(1): match.group(2) for match in re.finditer(rf"\b(\w+)\s*(?::=|=)\s*({_STRING})", text)}
    for match in _SUFFIX_CHECK.finditer(text):
        if source.code[match.start()] != text[match.start()] or not re.search(r"origin|host", match.group(2), re.I):
            continue
        value = values.get(match.group(3), match.group(3))
        if value[:1] not in ('"', "`"):
            continue
        literal = value[1:-1]
        if match.group(1) == "Contains" or not literal.startswith((".", "://")):
            yield ("permissive-cors", source.line_of(match.start()), f"strings.{match.group(1)} lets any origin that merely ends with or contains "
                   f"{literal!r} through, as https://evil{literal.lstrip('.')} does. Compare the whole origin against a fixed set.", {})
    for pattern in (_ANY_ORIGIN_FUNC, _WILDCARD_WITH_CREDENTIALS):
        for match in pattern.finditer(text):
            if pattern is _WILDCARD_WITH_CREDENTIALS or re.search(r"AllowCredentials\s*:\s*true", text):
                yield ("permissive-cors", source.line_of(match.start()), "Any origin is allowed together with credentials, so every site can make "
                       "requests with the user's cookies and read the answers. List the origins you serve.", {"severity": "high"})


# ---------------------------------------------------------------- errors and logs

_ERROR_RESPONSE = re.compile(r"\bhttp\.Error\(|\bc\.(?:JSON|String|AbortWithStatusJSON|IndentedJSON)\(\s*(?:http\.Status(?!OK\b|Created\b|Accepted\b|NoContent\b)\w+|[45]\d\d)\b")
_CONNECTION_DETAIL = re.compile(r"\b(?:\w*[dD]sn|\w*DSN|conn(?:ection)?[sS]tr(?:ing)?\w*|\w*Conn(?:ection)?Str(?:ing)?|\w*[dD](?:atabase|b)U[rR][lL]|\w*\.Password)\b")
_CONFIG_LOGGED = re.compile(r"""\b(?:log|logger|fmt|l)\.(?:Printf|Fatalf|Panicf|Infof|Debugf|Warnf|Errorf)\(\s*"[^"\n]{0,300}?%[+#]?v[^"\n]{0,300}"\s*,\s*([^\n]{1,200})""")
_CONFIG_NAME = re.compile(r"\*?(?:cfg|conf|config|settings|appConfig|[a-z]\w*Config|[a-z]\w*Cfg|[a-z]\w*Settings)")


def _exposed(source: Source, pairs: dict[int, int]) -> Iterator[tuple]:
    code = source.code
    for match in _ERROR_RESPONSE.finditer(code):
        opening = code.find("(", match.start())
        closing = pairs.get(opening, -1)
        if 0 < closing - opening < 3000 and _CONNECTION_DETAIL.search(code, opening, closing):
            yield ("error-details-exposed", source.line_of(match.start()), "This error response carries the connection string or a password, so the "
                   "caller learns credentials and internal hosts. Log the details server-side and return a short message.", {})
    for match in _CONFIG_LOGGED.finditer(source.text):
        logged = next((part.strip() for part in match.group(1).rstrip().rstrip(")").split(",") if _CONFIG_NAME.fullmatch(part.strip())), None)
        if source.code[match.start()] == source.text[match.start()] and logged:
            yield ("sensitive-log", source.line_of(match.start()), f"This logs the whole {logged.lstrip('*')} with %v, which prints every field, including "
                   "passwords, secrets and URLs with credentials. Log the fields that are safe to show, or give the type a String method that masks them.", {})


# ---------------------------------------------------------------- authorization that fails open

_REFUSES = re.compile(r"\bcodes\.(?:PermissionDenied|Unauthenticated)\b|\bhttp\.Status(?:Unauthorized|Forbidden)\b|\b(?:WriteHeader|AbortWithStatus\w*|Status)\(\s*40[13]\b")
_PASSES = re.compile(r"\bhandler\(\s*ctx\s*,\s*req\s*\)|\bnext\.ServeHTTP\(|\bnext\(\s*\w+|\bc\.Next\(\)|\binvoker\(")
_DECIDES = re.compile(r"(?<![\w.])(?:\w+\s*,\s*)?err\s*:?=\s*[^\n]{0,200}\b\w*(?:Check|Authoriz|Allow|Permit|Verif|Enforce|Can[A-Z]|IsMember|HasAccess|Validate|Introspect|Evaluate)\w*\(")
_STOPS = re.compile(r"\breturn\b|\bpanic\(|\bAbort\w*\(|\bhttp\.Error\(|\bos\.Exit\(|\blog\.Fatal|\bcontinue\b|\bbreak\b|\bgoto\b|\bWriteHeader\(")
_NEXT_CASE = re.compile(r"\bcase\b|\bdefault\s*:")
_ERROR_BRANCH = re.compile(r"\bif\s+err\s*!=\s*nil\s*\{|\bcase\s+err\s*!=\s*nil\s*:")


def _fail_open(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    code = source.code
    for function in functions:
        if not (_REFUSES.search(function.code) and _PASSES.search(function.code)):
            continue
        last_pass = max(match.start() for match in _PASSES.finditer(code, function.offset, function.body.end))
        for match in _ERROR_BRANCH.finditer(code, function.offset, function.body.end):
            decided = [found for found in _DECIDES.finditer(code, max(function.offset, match.start() - 600), match.start())]
            if not decided or last_pass < match.end():
                continue
            if match.group(0).startswith("if"):
                end = function.pairs.get(match.end() - 1, -1)
            else:
                following = _NEXT_CASE.search(code, match.end(), min(function.body.end, match.end() + 5000))
                end = following.start() if following else -1
            if end < 0 or not function.budget.spend(last_pass - match.end()):
                continue
            if not _STOPS.search(code, match.end(), end) and not _decided_again(code, decided[-1], end, last_pass):
                yield ("fail-open", source.line_of(match.start()), "When the authorization check errors, this branch only records it and the request "
                       "goes on to the handler, so an outage of the checker grants access. Refuse the request in this branch.", _MEDIUM)


def _decided_again(code: str, decided: re.Match, end: int, last_pass: int) -> bool:
    """`allowed, err := enforcer.Enforce(...)`, an error branch that only logs, then `if !allowed { deny }`: the decision is checked again
    before the handler runs, so an error that leaves it false (Go's convention) or sets it false is closed. A switch's later `case !allowed`
    isn't reached after the error case, and an `else if` isn't either."""
    named = re.match(r"(\w+)\s*,\s*err\b", decided.group(0))
    if not named or named.group(1) == "_":
        return False
    name = re.escape(named.group(1))
    if re.search(rf"(?<![\w.]){name}\s*=\s*true\b", code[decided.end():end]):
        return False
    again = re.compile(rf"\bif\s+(?:!\s*{name}\b|{name}\s*==\s*false\b|{name}\s*!=\s*true\b)")
    # `} else if !allowed` runs only when there was no error, so it doesn't check again after one.
    return any(not code[max(0, found.start() - 12):found.start()].rstrip().endswith("else") for found in again.finditer(code, end, last_pass))


# ---------------------------------------------------------------- predictable secrets

_MATH_RAND = re.compile(r'^[ \t]*(?:import[ \t]+)?(?:(\w+)[ \t]+)?"math/rand(?:/v2)?"', re.M)
_RANDOM_FIELD = re.compile(r"(\w+)\s*:\s*\w+\.New\(\s*\w+\.NewSource\(|(\w+)\s*=\s*\w+\.New\(\s*\w+\.NewSource\(")


def _insecure_random(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    alias = next((match.group(1) or "rand" for match in _MATH_RAND.finditer(source.text) if match.group(1) != "_"), None)
    if alias is None:
        return
    fields = {name for match in _RANDOM_FIELD.finditer(source.code) for name in match.groups() if name}
    uses = re.compile(rf"(?<![\w.]){re.escape(alias)}\.(?:Int\w*|Uint\w*|Float\w*|Read|Perm|Shuffle|N|Exp\w*|Norm\w*)\(" +
                      (rf"|\.(?:{'|'.join(map(re.escape, fields))})\.\w+\(" if fields else ""))
    random_functions = sorted({function.body.name for function in functions if uses.search(function.code)})[:50]
    calls = uses.pattern + (rf"|(?<![\w])(?:\w+\.)?(?:{'|'.join(map(re.escape, random_functions))})\(" if random_functions else "")
    random_call = re.compile(calls)
    for match in re.finditer(r"(?<![\w.])(\w+)\s*(?::=|=(?!=))\s*([^\n]{1,300})", source.code):
        if braced.secret_named(match.group(1)) and random_call.search(match.group(2)):
            yield ("insecure-random", source.line_of(match.start()), f"{match.group(1)} comes from math/rand, whose output can be predicted from a few "
                   "values or the seed. Use crypto/rand for anything that grants access.", {})


# ---------------------------------------------------------------- request bodies decoded into live state

_DECODE_INTO_FIELD = re.compile(r"(?:json\.NewDecoder\([^()\n]{0,80}\.Body[^()\n]{0,40}(?:\([^()\n]{0,60}\))?[^()\n]{0,20}\)\.Decode|\bc\.(?:ShouldBind\w*|Bind\w*))"
                                r"\(\s*&\s*(\w+)\.(\w+)\s*\)")
_BIND_INTO = re.compile(r"(?:json\.NewDecoder\([^()\n]{0,80}\.Body[^()\n]{0,40}(?:\([^()\n]{0,60}\))?[^()\n]{0,20}\)\.Decode|\bc\.(?:ShouldBind\w*|Bind\w*))\(\s*&\s*(\w+)\s*\)")
_DTO_TYPE = re.compile(r"(?:req|request|input|payload|params|body|dto|form|args|cmd|command|filter|query|patch|update|create)\w*$", re.I)
_MODEL_WRITE = re.compile(r"\.(?:Save|Create|Updates)\(\s*&?(\w+)\s*\)")
_DECLARED = re.compile(r"\bvar\s+(\w+)\s+([\w.]+)|(?<![\w.])(\w+)\s*:=\s*&?([\w.]+)\{")


def _mass_assignment(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    for function in functions:
        for match in _DECODE_INTO_FIELD.finditer(function.code):
            if function.receiver and match.group(1) == function.receiver:
                yield ("mass-assignment", source.line_of(function.offset + match.start()), f"This decodes the request body straight into the live "
                       f"{match.group(1)}.{match.group(2)}, so a client can set every field it holds, not only the ones this endpoint is for. Decode into a "
                       "struct of the allowed fields, validate them, and copy those across.", {})
        declared = {found.group(1) or found.group(3): found.group(2) or found.group(4) for found in _DECLARED.finditer(function.code)}
        saved = {found.group(1): found.start() for found in _MODEL_WRITE.finditer(function.code)}
        for match in _BIND_INTO.finditer(function.code):
            name = match.group(1)
            kind = declared.get(name, "")
            if kind and not _DTO_TYPE.search(kind.split(".")[-1]) and saved.get(name, -1) > match.end():
                yield ("mass-assignment", source.line_of(function.offset + match.start()), f"The request is bound straight into the model {kind} and saved, so a "
                       "client can set any column it maps, such as an owner or a role. Bind into a request struct and copy the allowed fields.", {})


# ---------------------------------------------------------------- shared maps

_PACKAGE_MAP = re.compile(r"^var[ \t]+(\w+)[ \t]*(?:=[ \t]*(?:map\[[^\]\n]{1,80}\][^{\n]{1,80}\{|make\(\s*map\[)|map\[[^\]\n]{1,80}\])", re.M)
_SERVES_CONCURRENTLY = re.compile(r"\bhttp\.ResponseWriter\b|\*gin\.Context\b|\becho\.Context\b|\*fiber\.Ctx\b|\bgrpc\.UnaryServerInfo\b|(?<![\w.])go\s+(?:func\b|\w+[\w.]*\()")
_MAP_WRITE = re.compile(r"(?<![\w.])(\w+)\[[^\]\n]{1,120}\]\s*(?:=(?!=)|\+\+|--|[+\-]=)|\bdelete\(\s*(\w+)\s*,")
_AT_STARTUP = re.compile(r"(?:init|[Rr]egister\w*|[Mm]ust\w*|[Ss]etup\w*|[Ll]oad\w*|[Ii]nit\w*|main|Test\w*)$")
_SYNCHRONIZED = re.compile(r"\bsync\.(?:Mutex|RWMutex|Map|Once)\b|\batomic\.|\bLock\(\)")


def _shared_maps(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    if not _SERVES_CONCURRENTLY.search(source.code) or _SYNCHRONIZED.search(source.code):
        return
    written: dict[str, set[str]] = {}  # map name: the functions that change it
    for function in functions:
        if not _AT_STARTUP.match(function.body.name):
            for write in _MAP_WRITE.finditer(function.code):
                written.setdefault(write.group(1) or write.group(2), set()).add(function.body.name)
    for match in _PACKAGE_MAP.finditer(source.code):
        writers = written.get(match.group(1))
        if writers:
            yield ("unsynchronized-state", source.line_of(match.start()), f"The package-level map {match.group(1)} is changed in {', '.join(sorted(set(writers))[:3])} "
                   "while requests run concurrently, with no lock, so concurrent writes race and Go stops with a fatal error. Guard it with a "
                   "sync.RWMutex, or keep it in a store.", {})


# ---------------------------------------------------------------- writes, transactions and races

_SQL_WRITE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|UPSERT|MERGE|REPLACE)\b", re.I)
_EXEC = re.compile(r"(?<![\w.])([\w.]{1,80})\.(?:Exec|ExecContext|MustExec|MustExecContext|NamedExec|NamedExecContext)\(")
_ORM_WRITE = re.compile(r"(?<![\w.])([\w.]{1,80})\.(?:Create|Save|Delete|Updates|Update|UpdateColumn|UpdateColumns)\(")
_ORM_HANDLE = re.compile(r"(?:^|\.)(?:db|gdb|gormDB|gormDb|orm|DB)$")
_TRANSACTION = re.compile(r"\bBegin(?:Tx)?\(|\.Transaction\(|\bWithTx\w*\(|\bInTx\w*\(|\bRunInTx\w*\(|\bExecTx\w*\(|\*sql\.Tx\b|\bpgx\.Tx\b|\bTxOptions\b|\bBeginFunc\(")


def _first_literal(source: Source, opening: int, pairs: dict[int, int]) -> str:
    for start, end in braced.arguments(source.code, opening, pairs)[:3]:
        literal = _STRING_RE.search(source.text, start, end)
        if literal:
            return literal.group(0)[1:-1]
    return ""


def _writes(source: Source, function: _Function) -> list[tuple[int, str]]:
    found = []
    for match in _EXEC.finditer(source.code, function.offset, function.body.end):
        receiver = match.group(1)
        if not re.search(r"(?:^|\.)\w*[tT]x$", receiver) and _SQL_WRITE.match(_first_literal(source, match.end() - 1, function.pairs)):
            found.append((match.start(), receiver))
    for match in _ORM_WRITE.finditer(source.code, function.offset, function.body.end):
        if _ORM_HANDLE.search(match.group(1)):
            found.append((match.start(), match.group(1)))
    return sorted(found)


def _without_transaction(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    for function in functions:
        writes = _writes(source, function)
        if len(writes) >= 2 and not _TRANSACTION.search(function.code) and not re.search(r"\btx\b", function.body.params):
            yield ("multi-write-no-transaction", source.line_of(writes[1][0]), f"{function.body.name} makes {len(writes)} separate writes with no transaction, so a "
                   "failure or crash between them leaves the first applied and the rest not. Run them in one transaction, or say why half done is safe.", {})


_FIELD_CHANGE = re.compile(r"(?<![\w.])(\w+)\.(\w+)\s*(?:\+\+|--|[+\-*/]=)")
_WRITE_BACK = re.compile(r"\.(?:Exec|ExecContext|Save|Updates|Update|UpdateColumn)\(")
_LOCKED = re.compile(r"FOR\s+UPDATE|FOR\s+NO\s+KEY\s+UPDATE|\bclause\.Locking\b|\bForUpdate\b|\bversion\s*=", re.I)


def _lost_update(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    if _LOCKED.search(source.text):
        return
    for function in functions:
        writes = [match.end() - 1 for match in _WRITE_BACK.finditer(source.code, function.offset, function.body.end)]
        for change in _FIELD_CHANGE.finditer(function.code):
            owner, field = change.group(1), change.group(2)
            at = bisect.bisect_left(writes, function.offset + change.end())
            if at == len(writes):
                continue
            opening = writes[at]  # the first write after the change
            closing = function.pairs.get(opening, -1)
            if closing < 0 or closing - opening > 3000:
                continue
            uses = re.search(rf"(?<![\w.]){re.escape(owner)}\.{re.escape(field)}\b|&{re.escape(owner)}\b|\(\s*{re.escape(owner)}\s*\)", source.code[opening:closing])
            statement = _first_literal(source, opening, function.pairs)[:2000]
            relative = re.search(r"\bSET\b[^;]{0,1000}?\b(\w+)\s*=\s*\1\s*[-+]", statement, re.I | re.S)
            if uses and not relative and (not statement or re.match(r"\s*UPDATE\b", statement, re.I)):
                yield ("lost-update", source.line_of(function.offset + change.start()), f"{owner}.{field} is read, changed here and written back as a value, "
                       "so two requests at once both start from the old value and one change is lost. Change it in the UPDATE itself (SET n = n - 1 "
                       "WHERE n > 0), or lock the row with SELECT ... FOR UPDATE in a transaction.", {})
                break


_ORM_LOOKUP = re.compile(r"\.\s*(?:First|Take|Find)\(\s*&(\w+)")
_SQL_LOOKUP = re.compile(r"\.QueryRow(?:Context)?\(")
_ABSENT = re.compile(r"\bErrRecordNotFound\b|\bsql\.ErrNoRows\b|\bpgx\.ErrNoRows\b|\berr\s*==\s*nil\b|\bcount\s*[>!=]=?\s*0\b|\bexists\b|\bfound\b", re.I)
_ORM_CREATE = re.compile(r"(?<![\w.])([\w.]{1,80})\.Create\(\s*&(?:(\w+)\s*\)|([\w.]+)\{)")
_EXEC_CALL = re.compile(r"\.(?:Exec|ExecContext)\(")
_CONSTRAINED = re.compile(r"\buniqueIndex\b|gorm:\"[^\"]*\bunique\b|\bErrDuplicatedKey\b|\b23505\b|unique_violation|UniqueViolation|duplicate key|Duplicate entry|IsUnique\w*|ON\s+CONFLICT|ON\s+DUPLICATE\s+KEY|INSERT\s+IGNORE", re.I)


def _model(name: str, code: str) -> str | None:
    """The type a variable was declared or built with: `var u User`, `u := User{...}`, `u := &models.User{}`, `u := new(User)`."""
    escaped = re.escape(name)
    found = re.search(rf"\bvar\s+{escaped}\s+\*?([\w.]+)|(?<![\w.]){escaped}\s*:?=\s*&?([\w.]+)\{{|(?<![\w.]){escaped}\s*:?=\s*new\(\s*([\w.]+)\s*\)", code)
    return next((group.split(".")[-1] for group in found.groups() if group), None) if found else None


def _table(source: Source, function: _Function, call: re.Match, keyword: str) -> str | None:
    statement = _first_literal(source, function.offset + call.end() - 1, function.pairs)[:2000]
    words = r"\s+".join(keyword.split())
    found = re.search(rf"\b{words}\s+[\"`]?(\w+)", statement, re.I)
    if keyword == "INSERT INTO" and not re.match(r"\s*INSERT\b", statement, re.I):
        return None
    return found.group(1) if found else None


def _check_then_insert(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    if _CONSTRAINED.search(source.text):
        return
    for function in functions:
        lookups = [(match.start(), _model(match.group(1), function.code)) for match in _ORM_LOOKUP.finditer(function.code)]
        lookups += [(match.start(), _table(source, function, match, "FROM")) for match in _SQL_LOOKUP.finditer(function.code)]
        lookups = [(at, model) for at, model in lookups if model]
        if not lookups:
            continue
        absent = _ABSENT.search(function.code, min(at for at, _ in lookups))
        if not absent:
            continue
        creates = [(match, _model(match.group(2), function.code) if match.group(2) else match.group(3)) for match in _ORM_CREATE.finditer(function.code, absent.end())
                   if _ORM_HANDLE.search(match.group(1))]
        creates += [(match, _table(source, function, match, "INSERT INTO")) for match in _EXEC_CALL.finditer(function.code, absent.end())]
        matched = [match for match, model in creates if model and any(at < match.start() and seen.lower() == model.lower() for at, seen in lookups)]
        for insert in matched[:1]:  # the same model or table, so a create of something else, such as an event row, isn't one
            yield ("check-then-insert", source.line_of(function.offset + insert.start()), "This looks the row up, and creates it only if it wasn't found, so "
                   "two requests at once both pass the check and both insert. Back it with a unique index and handle the duplicate-key error, or use ON CONFLICT.", {})


# ---------------------------------------------------------------- retried effects

_RETRY_CALL = re.compile(r"\bretry\.Do(?:WithData)?\(|\bbackoff\.Retry(?:Notify)?(?:WithData)?\w*\(|\bretry\.Retry\(|\bretrier\.Run\(")
_RETRY_LOOP = re.compile(r"\bfor\s+(?:(\w+)\s*:=\s*\d+\s*;\s*\w+\s*<=?\s*[\w.()]+\s*;\s*\w+\+\+|\w+\s*<=?\s*[\w.]+)\s*\{")
_RETRY_WORD = re.compile(r"retr|attempt|tries|try\b", re.I)
_WAITS = re.compile(r"\btime\.(?:Sleep|After)\(|[Bb]ackoff|\bjitter", re.I)
_EFFECT = re.compile(r"\bhttp\.MethodPost\b|\"POST\"|\bhttp\.Post(?:Form)?\(|\b\w*(?:[Cc]lient|[Aa]pi|API|[Ss]vc|[Ss]ervice|[Pp]rovider|[Gg]ateway|[Ss]ender|[Mm]ailer|[Pp]sp|[Ss]tripe)\."
                     r"(?:Create|Send|Charge|Refund|Pay|Transfer|Publish|Launch|Provision|Issue|Submit|Place|Capture|Withdraw|Deposit|Run|Post)\w*\(")
_IDEMPOTENT = re.compile(r"[Ii]dempoten|ClientToken|ClientRequestToken|RequestToken|[Dd]edup", re.I)


def _retried_effects(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    code = source.code
    for function in functions:
        if _IDEMPOTENT.search(source.text[function.offset:function.body.end]):
            continue
        spans = []
        for match in _RETRY_CALL.finditer(code, function.offset, function.body.end):
            closing = function.pairs.get(match.end() - 1, -1)
            if closing > 0:
                spans.append((match.start(), match.end(), closing, "is retried by " + match.group(0).rstrip("(")))
        for match in _RETRY_LOOP.finditer(code, function.offset, function.body.end):
            closing = function.pairs.get(match.end() - 1, -1)
            if closing > 0 and _RETRY_WORD.search(match.group(0)) and function.budget.spend(closing - match.end()) and _WAITS.search(code, match.end(), closing):
                spans.append((match.start(), match.end(), closing, "is retried in a loop"))
        for start, body_start, end, how in spans:
            if not function.budget.spend(end - body_start):
                return
            effect = _EFFECT.search(source.text, body_start, end)
            if effect and code[effect.start()] == source.text[effect.start()]:
                yield ("retry-not-idempotent", source.line_of(start), f"A call with an effect {how} with no idempotency key, so a timeout after the far side "
                       "acted repeats the effect. Send a key the far side deduplicates on, or retry only errors that prove nothing happened.", {})
                break


# ---------------------------------------------------------------- checkpoints and locks

_PROGRESS_SAVE = re.compile(r"(?<![\w.])([\w.]{1,80})\.(?:Set|SetEX|SetEx|HSet|Save\w{0,40}|Store\w{0,40}|Put\w{0,40}|Commit\w{0,40}|Update\w{0,40}|Write\w{0,40})\(\s*(?:ctx\s*,\s*)?[\w.\"]{0,60}?(?i:cursor|offset|checkpoint|watermark|last_?id|bookmark|progress)")
_LATER_EFFECT = re.compile(r"(?<![\w.])([\w.]{1,80})\.(?=\w{0,80}\()(\w{0,40}?(?:Create|Send|Post|Publish|Push|Upsert|Insert|Export|Sync|Import)\w{0,40}|Exec\w{0,20}|Do)\(")


def _checkpoint_first(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    for function in functions:
        if _TRANSACTION.search(function.code):
            continue
        for save in _PROGRESS_SAVE.finditer(function.code):
            if not function.budget.spend(len(function.code) - save.end()):
                return
            effect = next((match for match in _LATER_EFFECT.finditer(function.code, save.end())
                           if match.group(1) != save.group(1) and not re.search(r"log|logger|metrics|span", match.group(1), re.I)), None)
            if effect:
                yield ("checkpoint-before-effect", source.line_of(function.offset + save.start()), "The progress marker is saved before the work it covers "
                       f"({effect.group(0).rstrip('(')}) is done, so a crash or error between them skips that work for good. Save it after the effect "
                       "succeeds, or in the same transaction.", {})
                break


_SET_NX = re.compile(r"\.SetNX\(\s*\w+\s*,\s*([\w.]{1,80})")
_DEL = re.compile(r"\.Del\(\s*\w+\s*,\s*([\w.]{1,80})\s*\)")
_ETCD_MUTEX = re.compile(r"\bconcurrency\.NewMutex\(")


def _locks(source: Source) -> Iterator[tuple]:
    locked = {match.group(1) for match in _SET_NX.finditer(source.code)}
    for delete in _DEL.finditer(source.code):
        if delete.group(1) in locked:
            yield ("lock-without-fencing", source.line_of(delete.start()), "This deletes the lock key without checking it still holds the value this "
                   "process set, so after the lease expires it removes another holder's lock. Delete with a compare-and-delete script, and fence the "
                   "writes the lock protects with a token the store checks.", {})
    if _ETCD_MUTEX.search(source.code) and not re.search(r"\bIsOwner\(|\bHeader\(\)\.Revision|\bRevision\(\)", source.code):
        match = _ETCD_MUTEX.search(source.code)
        yield ("lock-without-fencing", source.line_of(match.start()), "Work done under this etcd mutex never checks it still owns the lock, so after the "
               "session expires a second holder runs at the same time. Condition the protected writes on mu.IsOwner() in a transaction, or on the "
               "lock's revision as a fencing token.", {})


# ---------------------------------------------------------------- cgo and acknowledgements

_GO_SIZE = {"int8": 1, "uint8": 1, "byte": 1, "int16": 2, "uint16": 2, "int32": 4, "uint32": 4, "rune": 4, "float32": 4.5,
            "int": 8, "uint": 8, "int64": 8, "uint64": 8, "uintptr": 8, "float64": 8.5}
_C_SIZE = {"char": 1, "schar": 1, "uchar": 1, "int8_t": 1, "uint8_t": 1, "short": 2, "ushort": 2, "int16_t": 2, "uint16_t": 2,
           "int": 4, "uint": 4, "int32_t": 4, "uint32_t": 4, "float": 4.5, "longlong": 8, "ulonglong": 8, "int64_t": 8, "uint64_t": 8,
           "double": 8.5, "size_t": 8, "intptr_t": 8, "uintptr_t": 8}
_CAST = re.compile(r"\(\*C\.(\w+)\)\(\s*unsafe\.Pointer\(\s*&(\w+)\[0\]\s*\)\s*\)")


def _native_types(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    if 'import "C"' not in source.text:
        return
    bodies = [function.body for function in functions]
    starts = [body.start for body in bodies]
    budget = braced.Budget(source.code)
    for match in _CAST.finditer(source.code):
        c_type, name = match.group(1), match.group(2)
        body = braced.enclosing(bodies, match.start(), starts)
        scope = source.code[body.head:body.end] if body else source.code
        if not budget.spend(len(scope)):
            return
        declared = re.search(rf"\b{re.escape(name)}\s+\[\](\w+)|\b{re.escape(name)}\s*:?=\s*make\(\s*\[\](\w+)|\bvar\s+{re.escape(name)}\s+\[\](\w+)", scope)
        go_type = next((group for group in declared.groups() if group), None) if declared else None
        if go_type in _GO_SIZE and c_type in _C_SIZE and _GO_SIZE[go_type] != _C_SIZE[c_type]:
            yield ("native-type-mismatch", source.line_of(match.start()), f"{name} holds Go {go_type} elements and is passed to C as *C.{c_type}, which "
                   "has a different size or kind, so C reads the wrong values. Copy into a []C." + c_type + " after checking each value fits.", {})


_UNACKNOWLEDGED = re.compile(r"\bwriteconcern\.Unacknowledged\(\)|\bwriteconcern\.W\(\s*0\s*\)|RequiredAcks\s*[:=]\s*(?:sarama\.NoResponse|kafka\.RequireNone)\b")


def _unacknowledged(source: Source) -> Iterator[tuple]:
    for match in _UNACKNOWLEDGED.finditer(source.code):
        yield ("unacknowledged-write", source.line_of(match.start()), "Writes here don't wait for the server to confirm them, so a write that fails is "
               "reported as saved. Wait for acknowledgement wherever the caller is told it succeeded.", {})


# ---------------------------------------------------------------- webhooks, downloads and uploads

_SIGNED_TIMESTAMP = re.compile(r"""\.Header\.Get\(\s*"[\w-]*[Tt]imestamp[\w-]*"\s*\)""")
_CLOCK = re.compile(r"\btime\.(?:Now|Since|Until|Unix\w*)\(|\.Now\(\)|\bclock\.")


def _replayable(source: Source) -> Iterator[tuple]:
    """A signed timestamp guards against replay only if something compares it with the clock."""
    if "hmac.New(" not in source.code or _CLOCK.search(source.code):
        return
    for match in _SIGNED_TIMESTAMP.finditer(source.text):
        if source.code[match.start()] == source.text[match.start()]:
            yield ("webhook-unverified", source.line_of(match.start()), "The request's signed timestamp is read but never compared with the clock, so "
                   "a captured request replays forever with a valid signature. Reject timestamps more than a few minutes from now.", {})
            return


# `if _, err := os.Stat(p); err == nil { return ... }`: the file being there is taken to mean it's done.
_STAT = re.compile(r"\bif\s+_\s*,\s*err\s*:?=\s*os\.Stat\(\s*(\w+)\s*\)\s*;\s*err\s*==\s*nil\s*\{\s*return\b")


def _downloads_in_place(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    """A file whose existence is taken to mean it's complete must appear all at once."""
    for function in functions:
        if re.search(r"\bos\.Rename\(|\bCreateTemp\(|\brenameio\b|\batomic\.\w*File", function.code):
            continue
        for stat in _STAT.finditer(function.code):
            if not function.budget.spend(len(function.code) - stat.end()):
                return
            name = re.escape(stat.group(1))
            write = re.compile(rf"\bos\.(?:Create\(\s*{name}\s*\)|WriteFile\(\s*{name}\s*,|OpenFile\(\s*{name}\s*,(?![^()\n]*O_EXCL))").search(function.code, stat.end())
            if write:  # O_EXCL makes a lock or marker file, whose existence is the point
                yield ("nonatomic-state-write", source.line_of(function.offset + write.start()), f"{stat.group(1)} is written in place, and its existence is "
                       "taken to mean it's complete, so an interrupted write is served as whole from then on. Write a temporary file in the same folder, "
                       "then os.Rename it over.", _MEDIUM)
                break


_FORM_FILE = re.compile(r"(?<![\w.])(\w+)\s*,\s*\w+\s*,\s*\w+\s*:?=\s*\w+\.FormFile\(|(?<![\w.])(\w+)\s*,\s*\w+\s*:?=\s*\w+\.Open\(\)")
_BOUNDED = re.compile(r"\bMaxBytesReader\(|\bLimitReader\(|\bCopyN\(|\bParseMultipartForm\(|\bMaxMultipartMemory\b|\.Size\b|\bLimitedReader\b")


def _unbounded_uploads(source: Source, functions: list[_Function]) -> Iterator[tuple]:
    for function in functions:
        if "FormFile(" not in function.code or _BOUNDED.search(function.code):
            continue
        names = {name for match in _FORM_FILE.finditer(function.code) for name in match.groups() if name}
        for name in names:
            read = re.search(rf"\bio\.ReadAll\(\s*{re.escape(name)}\s*\)|\bio\.Copy\(\s*[\w.]+\s*,\s*{re.escape(name)}\s*\)", function.code)
            if read:
                yield ("unbounded-upload", source.line_of(function.offset + read.start()), "This reads the whole upload with no size limit, so one large or "
                       "endless file exhausts memory or disk, whatever its extension says. Wrap the body in http.MaxBytesReader, and check the content's own "
                       "signature, not the name.", {})
                break


# ---------------------------------------------------------------- tests and passwords

_PRODUCTION_PROFILE = re.compile(r"""\b(?:WithSharedConfigProfile|WithProfile)\(\s*"(?:prod|production|live)\b[\w-]*"|"AWS_PROFILE"\s*,\s*"(?:prod|production|live)\b""")
_PASSWORD_DIGEST = re.compile(r"\b(?:md5|sha1|sha256|sha512)\.(?:Sum\w*|New\w*)\(\s*\[\]byte\(\s*[\w.]*(?i:password|passwd|pwd)\w*\s*\)")


def _tests(source: Source) -> Iterator[tuple]:
    for match in _PRODUCTION_PROFILE.finditer(source.text):
        yield ("live-credential-in-test", source.line_of(match.start()), "This test loads the production credentials profile, so running it reads and "
               "changes live data. Use a local emulator or a test account.", {})


def findings(source: Source, is_test: bool) -> Iterable[tuple]:
    """(rule, line, message, overrides) for one Go file."""
    if is_test:
        return list(_tests(source))
    pairs = braced.pairs(source.code)
    bodies = braced.functions(source, pairs)
    budget = braced.Budget(source.code)
    functions = [_Function(source, body, pairs, budget) for body in bodies]
    constants = _constants(source.code, pairs)
    found: list[tuple] = []
    for check in (lambda: _sql(source, functions, constants), lambda: _shell(source), lambda: _archive_paths(source, bodies), lambda: _ssrf(source, functions),
                  lambda: _cors(source), lambda: _exposed(source, pairs), lambda: _fail_open(source, functions), lambda: _insecure_random(source, functions),
                  lambda: _mass_assignment(source, functions), lambda: _shared_maps(source, functions), lambda: _without_transaction(source, functions),
                  lambda: _lost_update(source, functions), lambda: _check_then_insert(source, functions), lambda: _retried_effects(source, functions),
                  lambda: _checkpoint_first(source, functions), lambda: _locks(source), lambda: _native_types(source, functions), lambda: _unacknowledged(source),
                  lambda: _admin_routes(source), lambda: _replayable(source), lambda: _downloads_in_place(source, functions),
                  lambda: _unbounded_uploads(source, functions)):
        found += check()
    for match in _PASSWORD_DIGEST.finditer(source.code):
        found.append(("weak-password-hash", source.line_of(match.start()), "A password hashed with a fast digest can be brute-forced quickly. Use bcrypt, "
                      "scrypt or argon2 from golang.org/x/crypto.", _MEDIUM))
    return braced.one_per_line(found)
