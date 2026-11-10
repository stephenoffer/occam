"""Ruby and Rails checks that need more than one pattern: what a SQL string interpolates, which controller turns CSRF off, where a
path from params ends up, and a method's writes outside a transaction.

They report under the ids other languages use for the same failure. None is high severity with high confidence unless the request's
own params reach the sink on that line, so none sends an agent back at Stop otherwise.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Iterator
from typing import NamedTuple

from . import brackets
from .py_helpers import PLACEHOLDER_NAME, _has_sql
from .source import Source

MAX_METHOD = 20_000  # a method longer than this isn't read as one, so a file with no `end` can't make finding methods quadratic
MAX_STRING = 4_000
_MIGRATION_OR_SEED = re.compile(r"(?:^|/)db/(?:migrate/|seeds?(?:/|\.rb$))|(?:^|/)lib/tasks/")

_DEF = re.compile(r"^([ \t]*)def[ \t]+(?:self\.)?([\w?!=]+)", re.M)


# A value checked against a list before it reaches SQL: `col = SORTABLE.include?(c) ? c : "id"`, or a method doing that.
_ALLOWED_BY_LIST = re.compile(r"\binclude\?\(|\bpresence_in\(|\bin\?\(|\.fetch\(|%[wi][\[({]|\b[A-Z][A-Z0-9_]*(?:ALLOWED|COLUMNS|FIELDS|SORTS?|ORDERS?|DIRECTIONS?|WHITELIST|PERMITTED)\w*\b|\bcase\b")


class _Methods(NamedTuple):
    spans: list         # (name, start, end), in order of start
    starts: list
    allow_listed: set   # methods whose first lines check a value against a list, as a sort_column helper does

    def enclosing(self, offset: int) -> tuple[str, int, int] | None:
        index = bisect.bisect_right(self.starts, offset)
        inside = [method for method in self.spans[max(0, index - 8):index] if method[1] <= offset <= method[2]]
        return min(inside, key=lambda method: method[2] - method[1]) if inside else None


def _methods(code: str, text: str) -> _Methods:
    """Each method, ended by the `end` at its own indentation, as formatted Ruby is, found once per file."""
    found = []
    budget = 4 * len(code) + MAX_METHOD  # enough for real nesting, while defs with no `end` can't make this quadratic
    for match in _DEF.finditer(code):
        if budget <= 0:
            break
        line_end = code.find("\n", match.end())
        line_end = len(code) if line_end < 0 else line_end
        if re.search(r"(?:\bend|=[ \t]*[^\s=][^\n]*)[ \t]*$", code[match.end():line_end]):  # `def a; end` and `def a = b` end on their line
            found.append((match.group(2), match.start(), line_end))
            continue
        closer = re.compile(rf"^{re.escape(match.group(1))}end\b", re.M).search(code, line_end, min(len(code), line_end + MAX_METHOD))
        budget -= (closer.end() if closer else min(len(code), line_end + MAX_METHOD)) - line_end
        if closer:
            found.append((match.group(2), match.start(), closer.end()))
    allow_listed = set()
    for name, start, end in found:
        head_end = text.find("\n", start)
        opening = text[head_end:min(end, head_end + 800)] if head_end >= 0 else ""
        if _ALLOWED_BY_LIST.search("\n".join(opening.split("\n")[:9])):
            allow_listed.add(name)
    return _Methods(found, [method[1] for method in found], allow_listed)


# ---------------------------------------------------------------- SQL built by interpolation

# ActiveRecord methods whose string argument is SQL, called on a relation or, in a model's scope or class method, on self.
_SQL_SINK = re.compile(
    r"(?<![\w@$:])(?P<name>where|not|or|having|order|reorder|group|joins|from|select|pluck|lock|find_by|exists\?|find_by_sql|count_by_sql"
    r"|exec_query|execute|exec|exec_params|select_all|select_one|select_value|select_values|select_rows|update_all|delete_all)(?:[ \t]*\([ \t]*|[ \t]+)(?=\"|<<[~-]?)")
# Names that are SQL only when called on something, since bare `exec` is Kernel#exec and bare `select` is IO.select.
_NEEDS_RECEIVER = {"exec", "execute", "exec_query", "exec_params", "select_all", "select_one", "select_value", "select_values", "select_rows", "not", "or"}
# Names whose argument is SQL whatever it says. The rest have to read as SQL, so the Mail DSL's `from "#{name} <#{email}>"` isn't one.
_ALWAYS_SQL = {"where", "having", "order", "reorder", "group", "pluck", "find_by_sql", "count_by_sql", "not", "update_all", "delete_all"}
_CALLED_ON = re.compile(r"\.\s*$")
# SQL words and comparisons. A lone `<` or `>` isn't one: an email address in angle brackets has them.
_SQL_LOOK = re.compile(r"\b(?:SELECT|FROM|WHERE|JOIN|LIKE|ILIKE|BETWEEN|DISTINCT|ASC|DESC|AND|OR|IN|IS|NOT|NULL|AS|ON)\b"
                       r"|\b(?:COUNT|SUM|MAX|MIN|AVG|COALESCE|LOWER|UPPER)\s*\(|\w\s*(?:=|!=|<>|<=|>=)\s*[\w'(?:]", re.I)
# A bare `where(...)` is a query only where self is a model: a scope, a class method or a concern.
_MODEL = re.compile(r"<[ \t]*(?:ApplicationRecord|ActiveRecord::Base)\b|\bActiveSupport::Concern\b|^[ \t]*scope[ \t]+:", re.M)
_HEREDOC = re.compile(r"<<[~-]?(['\"]?)(\w+)\1")
_SAFE_SPLICE = re.compile(
    r"[A-Z][\w:]*"                                                                                       # a constant
    r"|(?:[\w:.]+\.)?(?:quoted_)?(?:table_name|primary_key|arel_table\.name)"                            # the model's own table
    r"|.*\.(?:to_i|to_f|to_r|id|size|length|count)|(?:Integer|Float)\(.*\)|\d+"                          # a number
    r"|.*\b(?:quote(?:_\w+)?|sanitize_sql(?:_array|_for_order)?|sanitize)\(.*|.*\bquote(?:_\w+)?\b.*"    # quoted
    r"|.*['\"]\?['\"].*|.*\bArray\.new\(.*\?.*"                                                         # placeholders, as `(['?'] * n).join(',')`
    r"|.*\.map\s*(?:\(\s*&:to_[ifr]\s*\)|\{\s*\|\s*\w+\s*\|\s*(?:\w+\.to_[ifr]|Integer\(\s*\w+\s*\)|Float\(\s*\w+\s*\))\s*\})(?:\.\w+(?:\([^()]*\))?)*", re.S)  # numbers, joined
_FROM_REQUEST = re.compile(r"\bparams\b|\brequest\.|\bcookies\[")


def _ruby_string(text: str, start: int) -> tuple[str, list[str], int]:
    """The double-quoted string at `start`: its written text, what it interpolates, and where it ends."""
    literal: list[str] = []
    spliced: list[str] = []
    index, limit = start + 1, min(len(text), start + MAX_STRING)
    piece = index
    while index < limit:
        character = text[index]
        if character == "\\":
            index += 2
        elif character == '"' or character == "\n":
            break
        elif text.startswith("#{", index):
            literal.append(text[piece:index])
            depth, inner = 1, index + 2
            while inner < limit and depth:
                depth += {"{": 1, "}": -1}.get(text[inner], 0)
                inner += 1
            spliced.append(text[index + 2:inner - 1].strip())
            index = piece = inner
        else:
            index += 1
    literal.append(text[piece:index])
    return "".join(literal), spliced, index + 1


def _heredoc(text: str, start: int, match: re.Match) -> tuple[str, list[str]]:
    """The heredoc opened at `match`, whose body starts on the next line. A single-quoted terminator interpolates nothing."""
    body_start = text.find("\n", start)
    if body_start < 0:
        return "", []
    terminator = re.compile(rf"^[ \t]*{re.escape(match.group(2))}[ \t]*$", re.M).search(text, body_start, min(len(text), body_start + MAX_STRING * 4))
    body = text[body_start:terminator.start() if terminator else body_start]
    if match.group(1) == "'":
        return body, []
    spliced = [found.strip() for found in re.findall(r"#\{([^{}\n]{0,300})\}", body)]
    return re.sub(r"#\{[^{}\n]{0,300}\}", " ", body), spliced


def _is_safe_splice(expression: str, in_method: str, methods: _Methods) -> bool:
    """A constant, a number, a quoted value, the model's own table, or a name this file checks against a list first."""
    expression = expression[:300]
    if not expression or _SAFE_SPLICE.fullmatch(expression) or PLACEHOLDER_NAME.fullmatch(expression):
        return True
    if re.fullmatch(r"@?\w+", expression):
        name = expression.lstrip("@")
        assigned = list(re.finditer(rf"(?<![\w.])@?{re.escape(name)}[ \t]*(?:\|\|)?=(?![=~>])([^\n]*)", in_method))
        if assigned and _ALLOWED_BY_LIST.search(assigned[-1].group(1)):
            return True
        return name in methods.allow_listed
    return False


def _sql_findings(source: Source, methods: _Methods) -> Iterator[tuple]:
    if _MIGRATION_OR_SEED.search(source.path):
        return
    text = source.text
    in_a_model = bool(_MODEL.search(source.code))
    for count, match in enumerate(_SQL_SINK.finditer(source.code)):
        if count >= 2000:
            return
        name = match.group("name")
        called_on = bool(_CALLED_ON.search(source.code[max(0, match.start() - 40):match.start()]))
        if not called_on and (name in _NEEDS_RECEIVER or not in_a_model):
            continue
        start = match.end()
        heredoc = _HEREDOC.match(text, start)
        if heredoc:
            literal, spliced = _heredoc(text, start, heredoc)
        else:
            literal, spliced, end = _ruby_string(text, start)
            joined = re.match(r"[ \t]*\+[ \t]*([^\s,)\"'][^,)\n]{0,200})", text[end:end + 300])
            if joined:
                spliced = spliced + [joined.group(1).strip()]
        if not spliced or not (name in _ALWAYS_SQL or _has_sql(literal) or _SQL_LOOK.search(literal)):
            continue
        method = methods.enclosing(match.start())
        in_method = text[max(method[1] if method else 0, match.start() - 5000):match.start()]
        unsafe = [part for part in spliced if not _is_safe_splice(part, in_method, methods)]
        if not unsafe:
            continue
        line = source.line_of(match.start())
        # Sure enough to send the agent back only when the request's value is spliced in on the sink's own line, not lines into a heredoc.
        on_the_line = not heredoc and any(_FROM_REQUEST.search(part) and part in source.line_text(line) for part in unsafe)
        shown = unsafe[0][:40]
        yield ("sql-injection", line, f"{name}() gets SQL with #{{{shown}}} interpolated into it. Pass values as bind "
               "parameters, as where(\"title ILIKE ?\", \"%#{q}%\"), and pick column names from a fixed list.", {} if on_the_line else {"confidence": "medium"})


# ---------------------------------------------------------------- params reaching models, files and markup

_PERMIT_ALL = re.compile(r"\.permit!(?![\w?!])")
_PERMIT = re.compile(r"\.permit\(")
_PRIVILEGED = re.compile(r"(?<![\w])[:\"']?(role|roles|role_id|role_ids|admin|is_admin|superuser|is_superuser|staff|is_staff|permissions|permission_ids|access_level|privileges?)(?:[\"']?\s*(?=[,)\]=]|$)|:\s)")
_ADMIN_ONLY = re.compile(r"(?:^|/)admin/|\bmodule[ \t]+Admin\b|\bAdmin::|before_action[ \t]+:(?:require|authorize|ensure|verify|check)_?\w*(?:admin|superuser|staff|owner)\w*|\bauthorize[ \t(!]|\bcan\?\(|\bpolicy\(")


def _mass_assignment(source: Source, paired: dict[int, int]) -> Iterator[tuple]:
    for match in _PERMIT_ALL.finditer(source.code):
        yield ("mass-assignment", source.line_of(match.start()), "permit! accepts every attribute the client sends, including ones such as owner_id, plan "
               "or role. List the fields a user may set.", {})
    if _ADMIN_ONLY.search(source.path) or _ADMIN_ONLY.search(source.code):
        return
    for match in _PERMIT.finditer(source.code):
        arguments = brackets.inside(source.text, paired, match.end() - 1, 1500)
        privileged = _PRIVILEGED.search(arguments)
        if privileged:
            yield ("mass-assignment", source.line_of(match.start()), f"Strong parameters permit :{privileged.group(1)}, so any user who can submit this form "
                   "can change their own privileges. Set it only in an action that checks the caller may.", {"confidence": "medium"})


# Where a path from params is opened, sent or joined. `.join` counts only on something named as a directory, since Array#join isn't a path.
_PATH_SINK = re.compile(
    r"(?:\bsend_file|\bsend_data|\bFile\.(?:read|binread|open|new|readlines|foreach|delete|unlink|write|binwrite)|\bIO\.(?:read|binread|readlines|foreach)"
    r"|\bFileUtils\.\w+|\bPathname(?:\.new)?|\bRails\.root\.join|\bFile\.join|\bFile\.expand_path|\b(?:[A-Z][A-Z0-9_]*|\w*(?:[dD]ir|[pP]ath|[rR]oot|[fF]older|[bB]ase)\w*)\.join"
    r"|\brender[ \t]+(?:file|template):)[ \t]*\(?([^\n]{0,240})")
_PARAM_VALUE = re.compile(r"\bparams(?:\[|\.(?:require|fetch|dig)\b)")
_CONTAINED = re.compile(r"\b(?:expand_path|realpath|cleanpath)\b[\s\S]{0,600}?\bstart_with\?|\bstart_with\?[\s\S]{0,600}?\b(?:expand_path|realpath|cleanpath)\b|\bascend\b")
_NAME_ONLY = re.compile(r"\b(?:File\.basename|basename|sanitize_filename|parameterize)\(\s*params|params(?:\[[^\]]*\])+\.(?:to_i|parameterize)\b")


def _path_traversal(source: Source, methods: _Methods) -> Iterator[tuple]:
    contained: dict[tuple, bool] = {}
    for count, match in enumerate(_PATH_SINK.finditer(source.code)):
        if count >= 2000:
            return
        argument = source.text[match.start(1):match.end(1)]
        if not _PARAM_VALUE.search(argument) or _NAME_ONLY.search(argument):
            continue
        method = methods.enclosing(match.start())
        span = (method[1], method[2]) if method else (max(0, match.start() - 3000), match.start() + 3000)
        if span not in contained:
            contained[span] = bool(_CONTAINED.search(source.code, span[0], min(span[1], span[0] + 20_000)))
        if contained[span]:
            continue
        yield ("path-traversal", source.line_of(match.start()), "A path built from params reaches the filesystem here, so ../ in it reads or writes outside "
               "the folder. Resolve it with File.expand_path and check it still starts with the folder, or look the file up by id.", {"confidence": "medium"})


# html_safe and raw mark text as already escaped. On an interpolated string or on params, it isn't.
_HTML_SAFE = re.compile(r"\.html_safe\b|(?<![\w.])raw[ \t]*\(|\brender[ \t]+(?:inline|html):")
# Parts that can't carry markup from a user: escaped, built by a view helper, or a number.
_ESCAPED = re.compile(r"^(?:h|html_escape|ERB::Util\.\w+|CGI\.escapeHTML|sanitize|strip_tags|escape_once|json_escape|j|escape_javascript|t|I18n\.t|number_\w+|link_to"
                      r"|content_tag|tag\.\w+|image_tag|safe_join)\b")
_HELPER_OR_NUMBER = re.compile(r"^[a-z_]\w*[?!]?\s*\(.*\)$|^\d+$|^@?\w*(?:count|total|size|length|number|num|amount|id|index|position|quantity|qty)$"
                               r"|^@?[\w.]+\.(?:to_i|to_f|id|count|size|length)$", re.S)


def _is_markup_safe(part: str) -> bool:
    part = part.strip()[:300]
    return bool(_ESCAPED.search(part) or (not _FROM_REQUEST.search(part) and _HELPER_OR_NUMBER.search(part)))


def _xss(source: Source) -> Iterator[tuple]:
    text = source.text
    for match in _HTML_SAFE.finditer(source.code):
        line = source.line_of(match.start())
        if match.group(0) == ".html_safe":
            whole = source.line_text(line)
            line_start = source.line_starts[line - 1]
            receiver = whole[:match.start() - line_start]
            blanked = source.code[line_start:match.start()].rstrip()  # string contents blanked, so the opening quote is the last one before the closing
            if blanked.endswith('"') and blanked.rfind('"', 0, len(blanked) - 1) >= 0:
                opening = blanked.rfind('"', 0, len(blanked) - 1)
                _, spliced, _ = _ruby_string(whole, opening)
                unsafe = [part for part in spliced if not _is_markup_safe(part)]
            else:
                unsafe = [receiver] if _FROM_REQUEST.search(receiver[-120:]) else []
        else:
            argument = text[match.end():match.end() + 240].split("\n", 1)[0]
            _, spliced, _ = _ruby_string(argument, argument.find('"')) if argument.lstrip().startswith('"') else ("", [], 0)
            unsafe = [part for part in spliced if not _is_markup_safe(part)] or ([argument] if _FROM_REQUEST.search(argument) else [])
        if unsafe:
            overrides = {} if any(_FROM_REQUEST.search(part) for part in unsafe) else {"confidence": "medium"}
            yield ("xss-sink", line, "Text that isn't escaped is marked as safe HTML here, so markup in it runs in the page. Escape each value with h(), "
                   "build the markup with content_tag, or sanitize it.", overrides)


# ---------------------------------------------------------------- CSRF, debug pages, password hashes, random tokens

_SKIPS_CSRF = re.compile(r"\bskip_before_action[ \t]+:verify_authenticity_token\b|\bskip_forgery_protection\b|\bprotect_from_forgery\b[^\n]*\bexcept:")
_FORGERY_OFF = re.compile(r"\ballow_forgery_protection[ \t]*=[ \t]*false\b")
# Machine-to-machine endpoints that carry no browser cookie, where turning the token off is how they work: named so in the path or the
# class, or authenticating by a token or signature instead of the session.
_MACHINE = r"webhook|callback|hook|notif|\bipn\b|omniauth|saml|\bsso\b|oauth|\bacs\b|(?:^|/|\b)api(?:/|\b|_)|stripe|paypal|twilio|slack|github|inbound|incoming"
_MACHINE_NAME = re.compile(_MACHINE, re.I)
_MACHINE_CLASS = re.compile(rf"^[ \t]*(?:class|module)\b[^\n]*(?:{_MACHINE}|ActionController::API)", re.I | re.M)
_TOKEN_AUTH = re.compile(r"authenticate_(?:or_request_)?with_http_(?:token|basic)|doorkeeper_authorize|verify_\w*signature|valid_signature|"
                         r"\bJWT\b|request\.headers\[\s*['\"](?:Authorization|X-[\w-]*(?:Token|Key|Signature))", re.I)


def _csrf(source: Source) -> Iterator[tuple]:
    if not (_MACHINE_NAME.search(source.path) or _MACHINE_CLASS.search(source.code) or _TOKEN_AUTH.search(source.text)):
        for match in _SKIPS_CSRF.finditer(source.code):
            if _MACHINE_NAME.search(source.line_text(source.line_of(match.start()))):
                continue  # only: :webhook, except: :callback
            yield ("disabled-control", source.line_of(match.start()), "This controller turns off Rails' CSRF check, so another site can make a signed-in "
                   "user's browser submit these actions. Keep it on for anything a session cookie authenticates.", {"confidence": "medium"})
    if not re.search(r"(?:^|/)environments/(?:test|development)\.rb$", source.path):
        for match in _FORGERY_OFF.finditer(source.code):
            yield ("disabled-control", source.line_of(match.start()), "CSRF protection is switched off for this whole environment.", {"confidence": "medium"})


_DEBUG_PAGES = re.compile(r"\bconsider_all_requests_local[ \t]*=[ \t]*true\b")
_OPEN_CONSOLE = re.compile(r"\b(?:web_console\.(?:whitelisted|allowed)_ips|BetterErrors::Middleware\.allow_ip!)[^\n]*0\.0\.0\.0/0")


def _debug(source: Source) -> Iterator[tuple]:
    for match in _OPEN_CONSOLE.finditer(source.text):
        yield ("debug-exposed", source.line_of(match.start()), "A debugging console that runs Ruby is open to every address.", {})
    if re.search(r"(?:^|/)config/(?:environments/(?!development\.rb$|test\.rb$)[\w.-]+\.rb|application\.rb)$", source.path):
        for match in _DEBUG_PAGES.finditer(source.code):
            yield ("debug-exposed", source.line_of(match.start()), "consider_all_requests_local = true outside development shows every visitor Rails' full "
                   "error page, with the backtrace, params and environment.", {})


_FAST_DIGEST = re.compile(r"\b(?:OpenSSL::)?Digest::(?:MD5|SHA1|SHA2|SHA256|SHA384|SHA512|RMD160)\.(?:hexdigest|digest|base64digest)\b"
                          r"|\bOpenSSL::Digest\.(?:hexdigest|digest)\b")
_PASSWORD_WORD = re.compile(r"pass(?:word|wd|phrase)\w*|\bpwd\b", re.I)
_STORES_A_PASSWORD = re.compile(r"\b(?:password|passwd)_(?:digest|hash|hashed|crypt)\w*[ \t]*=|\b(?:encrypted|crypted|hashed)_password[ \t]*=")
_SLOW_HASH = re.compile(r"\bBCrypt\b|\bbcrypt\b|has_secure_password|\bArgon2\b|\bargon2\b|\bSCrypt\b|\bscrypt\b|pbkdf2|PBKDF2|OpenSSL::KDF|\bdevise\b", re.I)


def _password_hash(source: Source) -> Iterator[tuple]:
    whole_file = bool(_STORES_A_PASSWORD.search(source.code)) and not _SLOW_HASH.search(source.code)
    for match in _FAST_DIGEST.finditer(source.code):
        line = source.line_of(match.start())
        if whole_file or (_PASSWORD_WORD.search(source.line_text(line)) and not _SLOW_HASH.search(source.line_text(line))):
            yield ("weak-password-hash", line, "A fast digest stores the password, so a leaked table is cracked at billions of guesses a second, salt or not. "
                   "Use has_secure_password or BCrypt.", {"confidence": "medium"})


_SECRET_TARGET = r"(?:token|secret|password|passwd|nonce|salt|otp|api_?key|(?:reset|verification|confirmation|login|invite|auth)_?code|session_?id)"
_WEAK_RANDOM = re.compile(
    rf"\b\w{{0,40}}{_SECRET_TARGET}(?!\w{{0,40}}(?:count|length|len|size|index|idx|delay|ttl|expir\w*|_at|_in|timeout|interval)\b)\w{{0,40}}[ \t]*(?:\|\|)?=(?![=~>])[^\n]{{0,160}}?(?:(?<![\w.:])rand\b|\bRandom\.(?:rand|new)\b|\bKernel\.rand\b|\.(?:sample|shuffle)\b(?![^\n]*random:))",
    re.I)


def _random(source: Source) -> Iterator[tuple]:
    for match in _WEAK_RANDOM.finditer(source.code):
        if "SecureRandom" not in source.line_text(source.line_of(match.start())):
            yield ("insecure-random", source.line_of(match.start()), "This secret comes from Ruby's default generator, which can be predicted from its "
                   "output. Use SecureRandom.", {"confidence": "medium"})


# ---------------------------------------------------------------- writes outside a transaction

# ActiveRecord writes that raise or touch many rows. `update` without a bang is Hash#update too, so it counts only on an instance variable.
_WRITE = re.compile(r"&?\.(?:update!|create!|destroy!|save!|delete_all|destroy_all|update_all|update_columns?|increment!|decrement!|toggle!|insert_all!?|"
                    r"upsert_all)(?![\w?!])|(?<=\w)\.(?:update|save|destroy)\b(?![?!])")
_SIDE_RECORD = re.compile(r"(?:Log|Audit|Event|Notification|Activity|History|Version)\w*$|^@?(?:log|audit|event|notification|activity)\w*$")
_RECEIVER = re.compile(r"(@?[A-Za-z_]\w*)[\w.&]*$")
_TRANSACTION = re.compile(r"\btransaction\b|\bwith_lock\b|\block!")
_CALLBACK = re.compile(r"\b(?:before|after|around)_(?:save|create|update|destroy|validation|commit|rollback)\b[^\n]*:(\w+[?!]?)")


def _writes_apart(source: Source, methods: _Methods) -> Iterator[tuple]:
    if _MIGRATION_OR_SEED.search(source.path):
        return
    callbacks = set(_CALLBACK.findall(source.code))
    for name, start, end in methods.spans:
        if name in callbacks or end - start > MAX_METHOD:
            continue
        body = source.code[start:end]
        if _TRANSACTION.search(body):
            continue
        receivers: list[tuple[str, int]] = []
        for write in _WRITE.finditer(body):
            line_start = body.rfind("\n", max(0, write.start() - 160), write.start()) + 1
            prefix = body[max(line_start, write.start() - 160):write.start()]
            for _ in range(3):
                prefix = re.sub(r"\([^()\n]{0,120}\)", "", prefix)
            receiver = _RECEIVER.search(prefix)
            if receiver and _SIDE_RECORD.search(receiver.group(1)):
                continue
            if receiver and (write.group(0).endswith(("!", "_all", "columns", "column")) or receiver.group(1).startswith("@")):
                receivers.append((receiver.group(1), write.start()))
        if len({receiver for receiver, _ in receivers}) >= 2:
            second = next(offset for receiver, offset in receivers if receiver != receivers[0][0])
            yield ("multi-write-no-transaction", source.line_of(start + second), f"{name} writes {len(receivers)} times to different records with no "
                   "transaction, so an error between them leaves the first done and the rest not. Wrap them in ApplicationRecord.transaction, or say "
                   "why half done is safe.", {})


# ---------------------------------------------------------------- files written in place, uploads in the web root, recorded HTTP

_WRITES_FILE = re.compile(r"\bFile\.(?:write|binwrite)\(\s*(@?[\w.]+)|\bFile\.open\(\s*(@?[\w.]+)\s*,\s*['\"]wb?\+?['\"]")
_REPLACED = re.compile(r"\bFile\.rename\b|\bFileUtils\.(?:mv|move)\b|\batomic_write\b|\bTempfile\b|\.rename\(")


def _nonatomic(source: Source, methods: _Methods) -> Iterator[tuple]:
    if _REPLACED.search(source.code):
        return
    for count, match in enumerate(_WRITES_FILE.finditer(source.text)):
        if count >= 300:
            return
        if source.code[match.start()].isspace():
            continue  # in a comment
        written = match.group(1) or match.group(2)
        target = re.escape(written)
        reads = rf"\b(?:File\.(?:read|binread|readlines|foreach)|IO\.read|YAML\.(?:load_file|safe_load_file)|JSON\.load_file)\(\s*{target}\s*[,)]|\bFile\.open\(\s*{target}\s*(?:\)|,\s*['\"]r)"
        method = methods.enclosing(match.start())
        local = re.fullmatch(r"[a-z_]\w*", written) and method  # another method's `path` is another file
        if re.search(reads, source.text[method[1]:method[2]] if local else source.text):
            yield ("nonatomic-state-write", source.line_of(match.start()), "This file is written in place and read back here, so a crash mid-write leaves "
                   "it truncated and the next read fails. Write a temporary file beside it and File.rename it over the original.", {"confidence": "medium"})


_CLIENT_NAME = re.compile(r"\.original_filename\b")
_PUBLIC_DIR = re.compile(r"""(?:Rails\.root\.join|File\.join)\(\s*['"]public['"]|Rails\.public_path|['"]public/""")


def _upload_in_webroot(source: Source) -> Iterator[tuple]:
    if not _CLIENT_NAME.search(source.code):
        return
    for match in _PUBLIC_DIR.finditer(source.text):
        line = source.line_of(match.start())
        if re.search(r"\bFile\.(?:open|write|binwrite)|FileUtils\.(?:cp|mv|copy|move)|\.(?:join)", source.line_text(line)):
            yield ("upload-in-webroot", line, "An upload is stored under public/ with the name the client gave it, so an .html or .svg file with script "
                   "is served from this site. Store uploads outside public, or name them yourself with an extension from a fixed list.", {})


_VCR = re.compile(r"\bVCR\.configure\b")
_VCR_FILTERED = re.compile(r"\b(?:filter_sensitive_data|define_cassette_placeholder|before_record|before_http_request)\b")


def _vcr(source: Source) -> Iterator[tuple]:
    match = _VCR.search(source.code)
    if match and not _VCR_FILTERED.search(source.code):
        yield ("vcr-unfiltered", source.line_of(match.start()), "VCR records real requests into committed cassettes, and nothing here filters the "
               "Authorization header or API keys, so the next recording against a live service commits its credential. Add filter_sensitive_data "
               "for each one.", {})


def findings(source: Source, is_test: bool, is_script: bool) -> Iterable[tuple]:
    """Yield (rule, line, message, overrides) for one Ruby file."""
    if is_test:
        yield from _vcr(source)
        return
    methods = _methods(source.code, source.text)
    yield from _sql_findings(source, methods)
    yield from _mass_assignment(source, brackets.pairs(source.code))
    yield from _path_traversal(source, methods)
    yield from _xss(source)
    yield from _csrf(source)
    yield from _debug(source)
    yield from _password_hash(source)
    yield from _random(source)
    yield from _upload_in_webroot(source)
    yield from _nonatomic(source, methods)
    if not is_script:
        yield from _writes_apart(source, methods)
    yield from _vcr(source)  # a spec/support file outside spec/ still configures the suite
