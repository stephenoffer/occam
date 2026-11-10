"""PHP and Laravel checks that need more than one pattern: SQL built into a query string, Blade's unescaped echo, the CSRF middleware's
exemptions, and assert() standing in for a check.

There is no PHP corpus or interpreter on the machine these were written on, so each one is narrow: a sink that the framework documents
as raw, and a value that plainly comes from the request or isn't escaped. They report under the ids other languages use for the same
failure, and none is high severity with high confidence unless the request reaches the sink on that line.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from . import brackets
from .py_helpers import PLACEHOLDER_NAME, _has_sql
from .source import Source

MAX_STRING = 4_000
_REQUEST = re.compile(r"\$_(?:GET|POST|REQUEST|COOKIE|FILES|SERVER)\b|\$request->(?:input|get|query|post|cookie|route|all|string|integer)\b|\brequest\(\)->|\bInput::|\$this->request->")

# ---------------------------------------------------------------- SQL

# Laravel's documented raw entry points, PDO and mysqli. The generic names (`->query`, `->exec`, `->prepare`) count only for text that reads as SQL.
_SQL_SINK = re.compile(r"\bDB::(?:raw|select|selectOne|statement|insert|update|delete|unprepared|scalar)\s*\("
                       r"|->(?:whereRaw|orWhereRaw|havingRaw|orHavingRaw|orderByRaw|selectRaw|groupByRaw|fromRaw)\s*\("
                       r"|(?<![\w$])(?:mysqli_query|mysqli_real_query|mysqli_multi_query|mysql_query|pg_query|sqlite_query)\s*\((?:\s*\$\w+\s*,)?"
                       r"|->(?P<generic>query|exec|prepare|multi_query|real_query|get_results|get_row|get_var|get_col)\s*\(")  # the last four are WordPress's $wpdb
# Class constants (self::TABLE, static::TABLE, Order::TABLE) name tables, not input.
_SAFE_PART = re.compile(r"\b(?:self|static|parent|[A-Z]\w*)::[A-Z_][A-Z0-9_]*\b(?!\s*\()|\$wpdb->\w+|->prefix\b|\(int\)|\(float\)|\bintval\(|\bfloatval\(|->quote\(|\bquote\(|\bPDO::PARAM_|\barray_fill\(|\bstr_repeat\(\s*['\"]\?|\$this->table\b|\$table\b|::\$table\b"
                        r"|\$(?:\w*[Pp]laceholders?|\w*[Mm]arks|in)\b|\bimplode\(\s*['\"],\s*['\"]\s*,\s*array_fill")


def _php_string(text: str, start: int) -> tuple[str, list[str], int]:
    """The quoted string at `start`: its written text, what a double-quoted one interpolates, and where it ends."""
    quote = text[start]
    literal: list[str] = []
    spliced: list[str] = []
    index, limit = start + 1, min(len(text), start + MAX_STRING)
    piece = index
    while index < limit:
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == quote:
            break
        if quote == '"' and character == "$" and index + 1 < limit and (text[index + 1].isalpha() or text[index + 1] == "_"):
            found = re.match(r"\$\w+(?:->\w+|\[[^\]\n]{0,60}\])*", text[index:index + 200])
            literal.append(text[piece:index])
            spliced.append(found.group(0))
            index = piece = index + len(found.group(0))
            continue
        if quote == '"' and text.startswith("{$", index):
            close = text.find("}", index, limit)
            close = limit if close < 0 else close
            literal.append(text[piece:index])
            spliced.append(text[index + 1:close])
            index = piece = close + 1
            continue
        index += 1
    literal.append(text[piece:index])
    return "".join(literal), spliced, index + 1


_OPERAND = re.compile(r"(?:\(\s*(?:int|float|string)\s*\)\s*)?(?:\$?[\w\\]+|\$\{[^}\n]{0,80}\})(?:(?:->|::)\$?\w+|\[[^\]\n]{0,80}\]|\([^()\n]{0,200}\))*")


def _sql_argument(text: str, start: int) -> tuple[str, list[str], bool]:
    """The first argument at `start`: its literal text, what's interpolated or concatenated into it, and whether any of it is a string."""
    literal: list[str] = []
    spliced: list[str] = []
    quoted = False
    index = start
    limit = min(len(text), start + MAX_STRING)
    while index < limit:
        while index < limit and text[index] in " \t\r\n":
            index += 1
        if index < limit and text[index] in "'\"":
            written, parts, index = _php_string(text, index)
            literal.append(written)
            spliced += parts
            quoted = True
        else:
            operand = _OPERAND.match(text, index, min(limit, index + 400))
            if not operand or not operand.group(0).strip():
                break
            spliced.append(operand.group(0).strip())
            index = operand.end()
        joined = re.match(r"\s*\.(?![=\d])\s*", text[index:index + 50])
        if not joined:
            break
        index += len(joined.group(0))
    return " ".join(literal), [part for part in spliced if part], quoted


# What a variable may hold when every assignment to it in the file is a table name: a literal, a constant, or WordPress's prefix plus a
# literal, as `$table_name = $wpdb->prefix . 'orders';`.
_ASSIGNED = re.compile(r"\$(\w+)\s*=(?![=>])\s*([^;\n]{0,200});")
_TABLE_VALUE = re.compile(r"""(?:\$wpdb->\w+|(?:self|static|parent|[A-Z]\w*)::[A-Z_][A-Z0-9_]*|['"][\w.]{0,80}['"]|[A-Z_][A-Z0-9_]*)"""
                          r"""(?:\s*\.\s*(?:['"][\w.]{0,80}['"]|\$wpdb->\w+|(?:self|static|parent|[A-Z]\w*)::[A-Z_][A-Z0-9_]*))*\s*""")


def _table_variables(source: Source) -> set[str]:
    values: dict[str, bool] = {}
    for match in _ASSIGNED.finditer(source.text):
        safe = bool(_TABLE_VALUE.fullmatch(match.group(2)))
        values[match.group(1)] = values.get(match.group(1), True) and safe
    return {name for name, safe in values.items() if safe}


def _sql(source: Source) -> Iterator[tuple]:
    tables = None
    for count, match in enumerate(_SQL_SINK.finditer(source.code)):
        if count >= 2000:
            return
        literal, spliced, quoted = _sql_argument(source.text, match.end())
        if not spliced or not (quoted or any(_REQUEST.search(part) for part in spliced)):
            continue  # a bare variable holding a prepared string
        if match.group("generic") and not _has_sql(literal):
            continue
        if tables is None:
            tables = _table_variables(source)
        unsafe = [part for part in spliced if not _SAFE_PART.search(part) and not PLACEHOLDER_NAME.fullmatch(part.lstrip("$"))
                  and not (re.fullmatch(r"\{?\$(\w+)\}?", part) and re.fullmatch(r"\{?\$(\w+)\}?", part).group(1) in tables)]
        if not unsafe:
            continue
        line = source.line_of(match.start())
        # Sure enough to send the agent back only when the request's value is on the sink's own line.
        on_the_line = any(_REQUEST.search(part) and part in source.line_text(line) for part in unsafe)
        overrides = {} if on_the_line else {"confidence": "medium"}
        yield ("sql-injection", line, f"This query is built with {unsafe[0][:40]} spliced into its text. Bind it as a "
               "parameter, as where('name', $name) or whereRaw('lower(name) = ?', [$name]).", overrides)


# ---------------------------------------------------------------- output

# Blade's {!! !!} prints without escaping. These helpers return markup the framework or the app built, not text from a user.
_RAW_BLADE = re.compile(r"\{!!(.{0,400}?)!!\}")
_BUILT_MARKUP = re.compile(r"^\s*(?:csrf_field|method_field|Form::\w+|Html::\w+|\$\w+->links|\$\w+->render|json_encode|Js::from|__|trans|trans_choice|@lang|"
                           r"config|route|url|asset|mix|vite|\$slot|\$attributes|\$\w*(?:svg|icon)\w*)\b|^\s*\$\w*(?:->|::)?\w*(?:[Ss]vg|[Ii]con)\b"
                           r"|\b(?:clean|Purifier::clean|purify|sanitize\w*|e|htmlspecialchars|htmlentities|strip_tags|esc_html|esc_attr)\s*\(", re.S)
_ECHO_REQUEST = re.compile(r"(?:\becho\b|\bprint\b|<\?=)\s*\(?\s*\$_(?:GET|POST|REQUEST|COOKIE)\b|(?:\becho\b|<\?=)\s*\$_SERVER\[\s*['\"](?:PHP_SELF|REQUEST_URI|QUERY_STRING|HTTP_\w+)")


# What reaches the page as stored text: a variable or a property, bare or through functions that keep markup, as nl2br($post->body).
# A method call's result, as $chart->container(), is markup some library built.
_PASSES_MARKUP = r"(?:nl2br|Str::markdown|Markdown::\w+|markdown|html_entity_decode|htmlspecialchars_decode|str_replace|preg_replace|ucfirst|trim|Str::limit|Str::words)"
_STORED_TEXT = re.compile(rf"^\s*(?:{_PASSES_MARKUP}\s*\(\s*)*\$\w+(?:->\w+|\[[^\]\n]{{1,60}}\])*\s*(?:[,)]|$)")


def _xss(source: Source) -> Iterator[tuple]:
    if source.path.endswith(".blade.php"):
        for match in _RAW_BLADE.finditer(source.text):
            if _STORED_TEXT.match(match.group(1)) and not _BUILT_MARKUP.search(match.group(1)):
                yield ("xss-sink", source.line_of(match.start()), f"{{!! {match.group(1).strip()[:40]} !!}} prints without escaping, so markup in it runs "
                       "for everyone who views the page. Use {{ }}, or clean it with an HTML sanitizer first.", {"confidence": "medium"})
    for match in _ECHO_REQUEST.finditer(source.text):
        if not re.search(r"htmlspecialchars|htmlentities|\be\(|strip_tags|intval|\(int\)", source.line_text(source.line_of(match.start()))):
            yield ("xss-sink", source.line_of(match.start()), "Request input is echoed into the page unescaped. Wrap it in htmlspecialchars.", {})


# ---------------------------------------------------------------- CSRF, debug output, assert, passwords, random tokens

_CSRF_LIST = re.compile(r"(?:protected\s+\$except\s*=|\bvalidateCsrfTokens\s*\(\s*except\s*:)\s*\[")
# Endpoints a provider or another server calls, with no browser cookie, where exempting them is how they work.
_MACHINE = re.compile(r"webhook|hook|callback|notify|notification|\bipn\b|stripe|paypal|braintree|mollie|razorpay|paddle|twilio|mailgun|sendgrid|postmark|"
                      r"\bsns\b|\bses\b|slack|github|gitlab|telegram|discord|^/?api(?:/|$)|oauth|saml|\bsso\b|\bacs\b|\bcron\b|health|ping", re.I)


def _csrf(source: Source) -> Iterator[tuple]:
    if not re.search(r"VerifyCsrfToken|ValidateCsrfToken|validateCsrfTokens", source.code):
        return
    for match in _CSRF_LIST.finditer(source.code):
        close = source.text.find("]", match.end(), match.end() + 4000)
        entries = re.findall(r"""['"]([^'"\n]{1,200})['"]""", source.text[match.end():close if close > 0 else match.end()])
        browser = [entry for entry in entries if not _MACHINE.search(entry)]
        if browser:
            yield ("disabled-control", source.line_of(match.start()), f"The CSRF middleware exempts {', '.join(browser[:3])}, routes that read like "
                   "ordinary session-cookie pages, so another site can submit them as a signed-in user. Exempt only endpoints with no browser session, "
                   "such as a signed webhook.", {"confidence": "medium"})


_DISPLAY_ERRORS = re.compile(r"""\bini_set\(\s*['"]display_errors['"]\s*,\s*(?:['"]?(?:1|on|true|stdout)['"]?|true)\s*\)""", re.I)
_DEBUG_ON = re.compile(r"""['"]debug['"]\s*=>\s*true\b""")
_WP_DEBUG = re.compile(r"""\bdefine\(\s*['"]WP_DEBUG(?:_DISPLAY)?['"]\s*,\s*true\s*\)""")


def _debug(source: Source, is_script: bool) -> Iterator[tuple]:
    if is_script:
        return
    for match in _DISPLAY_ERRORS.finditer(source.text):
        yield ("debug-exposed", source.line_of(match.start()), "display_errors is on, so every visitor sees PHP's errors, with paths and values.", {})
    if re.search(r"(?:^|/)config/app\.php$", source.path):
        for match in _DEBUG_ON.finditer(source.text):
            yield ("debug-exposed", source.line_of(match.start()), "debug is hard-coded on, so every visitor gets the full error page with the "
                   "environment. Read it from APP_DEBUG, off by default.", {})
    if source.path.endswith("wp-config.php"):
        for match in _WP_DEBUG.finditer(source.text):
            yield ("debug-exposed", source.line_of(match.start()), "WordPress debugging is on, so errors and paths are shown to visitors.", {})


_ASSERT = re.compile(r"(?<![\w>:$])assert\s*\(")
# `assert($x instanceof Foo)` narrows a type for a static analyzer, which is what modern PHP uses assert for.
_TYPE_CLAUSE = re.compile(r"\s*!?\s*(?:\$[\w>-]+\s+instanceof\s+[\w\\]+|\(?\s*is_\w+\(\s*\$[\w>-]+\s*\)|\$[\w>-]+\s*[!=]==?\s*null|null\s*[!=]==?\s*\$[\w>-]+)\s*\)?\s*")
_ACCESS = re.compile(r"->(?:can|cannot|authorize|allows|denies|isAdmin|hasRole|hasPermission\w*|hasAnyRole|is_admin|owns\w*)\s*\(|\bGate::|\bAuth::|\bauth\(\)|"
                     r"->user\(\)|\$user\b|\buser_id\b|->role\b|->tenant\w*|->owner\w*", re.I)
_FUNCTION_HEAD = re.compile(r"\bfunction\s+&?\w+\s*\(([^)]{0,500})\)")


def _assert(source: Source, paired: dict[int, int]) -> Iterator[tuple]:
    for count, match in enumerate(_ASSERT.finditer(source.code)):
        if count >= 500:
            return
        condition = brackets.inside(source.code, paired, match.end() - 1)
        line = source.line_of(match.start())
        first = re.split(r",(?![^()]*\))", condition, maxsplit=1)[0]
        if all(_TYPE_CLAUSE.fullmatch(clause) for clause in re.split(r"&&|\|\||\band\b|\bor\b", first)):
            continue
        if _ACCESS.search(first):
            yield ("assert-validation", line, "This access check is an assert(), and production PHP runs with zend.assertions = -1, which skips it "
                   "and lets everyone through. Throw or deny instead.", {"severity": "high", "confidence": "medium"})
            continue
        heads = list(_FUNCTION_HEAD.finditer(source.code, max(0, match.start() - 20_000), match.start()))
        params = set(re.findall(r"\$(\w+)", heads[-1].group(1))) if heads else set()
        if _REQUEST.search(first) or params & set(re.findall(r"\$(\w+)", first)):
            yield ("assert-validation", line, "This check of input is an assert(), which production PHP skips (zend.assertions = -1). Throw an "
                   "exception or return an error instead.", {"severity": "medium", "confidence": "medium"})


_FAST_PASSWORD_HASH = re.compile(r"(?<![\w>:$])(?:md5|sha1|crc32)\s*\([^;\n]{0,120}?\$\w{0,40}pass(?:word|wd|phrase)?\w{0,40}\b"
                                 r"|\bhash\(\s*['\"](?:md5|sha1|sha224|sha256|sha384|sha512|ripemd160|whirlpool)['\"]\s*,[^;\n]{0,120}?\$\w{0,40}pass(?:word|wd|phrase)?\w{0,40}\b", re.I)


def _password_hash(source: Source) -> Iterator[tuple]:
    for match in _FAST_PASSWORD_HASH.finditer(source.code):
        yield ("weak-password-hash", source.line_of(match.start()), "A fast hash stores the password, so a leaked table is cracked at billions of "
               "guesses a second. Use password_hash() and password_verify().", {"confidence": "medium"})


_SECRET_NAME = r"(?:token|secret|password|passwd|nonce|salt|otp|api_?key|remember|reset|csrf|session_?id|(?:verification|activation|confirm\w*|login|auth|sms|email)_?code)"
_WEAK_RANDOM = re.compile(rf"""(?:\$\w{{0,40}}{_SECRET_NAME}\w{{0,40}}\s*=(?!=)|['"]\w{{0,40}}{_SECRET_NAME}\w{{0,40}}['"]\s*=>)[^;\n]{{0,160}}?(?<![\w>:$])(?:rand|mt_rand|uniqid|lcg_value|str_shuffle|array_rand|shuffle|microtime)\s*\(""", re.I)
_STRONG_RANDOM = re.compile(r"\brandom_bytes\b|\brandom_int\b|\bopenssl_random_pseudo_bytes\b|\bStr::random\b|\bsodium_")


def _random(source: Source) -> Iterator[tuple]:
    for match in _WEAK_RANDOM.finditer(source.text):
        if source.code[match.start():match.start() + 1].isspace():
            continue  # in a comment
        if not _STRONG_RANDOM.search(source.line_text(source.line_of(match.start()))):
            yield ("insecure-random", source.line_of(match.start()), "This secret is made from the clock or a non-cryptographic generator, so it "
                   "can be guessed. Use random_bytes() or random_int().", {"confidence": "medium"})


_PATH_SINK = re.compile(r"(?<![\w>:$])(?:file_get_contents|readfile|fopen|file|unlink|fpassthru|show_source|highlight_file|include|include_once|require|require_once)\b"
                        r"\s*\(?([^;\n]{0,240})|(?:Storage::(?:disk\([^)\n]{0,60}\)->)?(?:get|download|delete|readStream|path)|response\(\)->(?:download|file))\s*\(([^;\n]{0,240})")
_NAME_ONLY = re.compile(r"\bbasename\s*\(|\bintval\s*\(|\(int\)")


def _path_traversal(source: Source) -> Iterator[tuple]:
    for match in _PATH_SINK.finditer(source.text):
        argument = match.group(1) or match.group(2) or ""
        if source.code[match.start():match.start() + 1].isspace() or not _REQUEST.search(argument) or _NAME_ONLY.search(argument):
            continue
        yield ("path-traversal", source.line_of(match.start()), "A path from the request reaches the filesystem here, so ../ in it reaches other "
               "files. Use basename(), or resolve it with realpath() and check it stays under the folder.", {"confidence": "medium"})


_CLIENT_NAME = re.compile(r"getClientOriginalName\s*\(|getClientOriginalExtension\s*\(|\$_FILES\s*\[[^\]\n]{1,60}\]\s*\[\s*['\"]name['\"]\s*\]"
                          r"|\$\w{0,40}(?:file|upload|attachment|image|img|avatar|photo|doc)\w{0,40}\s*\[\s*['\"]name['\"]\s*\]", re.I)
_WEBROOT = r"(?:public_path\s*\(|\$_SERVER\s*\[\s*['\"]DOCUMENT_ROOT['\"]|['\"/](?:public|htdocs|www|public_html)/)"
_WEBROOT_VARIABLE = re.compile(rf"\$(\w+)\s*=\s*[^;\n]{{0,120}}{_WEBROOT}")
_MOVE = re.compile(r"->move\s*\(([^;\n]{0,240})|\bmove_uploaded_file\s*\([^,;\n]{0,200},([^;\n]{0,240})|->(?:storeAs|storePubliclyAs|putFileAs)\s*\(([^;\n]{0,240}['\"]public['\"][^;\n]{0,60})"
                   r"|Storage::disk\(\s*['\"]public['\"]\s*\)->(?:putFileAs|put|move)\s*\(([^;\n]{0,240})")


def _upload_in_webroot(source: Source) -> Iterator[tuple]:
    if not _CLIENT_NAME.search(source.text):
        return
    webroot = {match.group(1) for match in _WEBROOT_VARIABLE.finditer(source.text)}
    for match in _MOVE.finditer(source.text):
        if source.code[match.start():match.start() + 1].isspace():
            continue  # in a comment or a string
        destination = next(group for group in match.groups() if group is not None)
        public_disk = match.group(3) is not None or match.group(4) is not None
        if public_disk or re.search(_WEBROOT, destination) or any(re.search(rf"\${re.escape(name)}\b", destination) for name in webroot):
            yield ("upload-in-webroot", source.line_of(match.start()), "An upload is stored in the public web root under the name or extension the "
                   "client sent, so an .svg, .html or .php file is served from this site. Store it outside public/, and choose the extension from "
                   "the checked content type.", {})


def findings(source: Source, is_test: bool, is_script: bool) -> Iterable[tuple]:
    """Yield (rule, line, message, overrides) for one PHP file."""
    if is_test:
        return
    yield from _sql(source)
    yield from _xss(source)
    yield from _csrf(source)
    yield from _debug(source, is_script)
    yield from _assert(source, brackets.pairs(source.code) if "assert" in source.code else {})
    yield from _password_hash(source)
    yield from _random(source)
    yield from _path_traversal(source)
    yield from _upload_in_webroot(source)
