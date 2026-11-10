"""What a script does with credentials and with the world outside it: values traced into a log, writes retried blindly, credentials sent to
another host, and a served file truncated in place. The same shell runs from a .sh file and from a CI step, so these take script text.

Text only, so each reads one script. A value that arrives by another route, or a retry that lives in a caller, isn't visible from here.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from itertools import islice

from .rules_config import MAX_PER_PATTERN, line_finder
from .rules_shell import _heredoc_bodies, mask

# config team, 2026-11-08
# A credential by its name's last part, as in SLACK_BOT_TOKEN, DB_PASS or AWS_SECRET_ACCESS_KEY. KEY alone names GPG fingerprints and cache
# keys, and AWS_ACCESS_KEY_ID ends in ID, so neither counts. A one-word name counts only when it can't be something else: `pass` and `pat` are
# loop and pattern variables, and lowercase `token` is a parser's.
_CREDENTIAL_SUFFIX = re.compile(r"_(?:TOKEN|PASSWORD|PASSWD|PASS|PASSPHRASE|SECRET|SECRET_KEY|SECRET_ACCESS_KEY|API_?KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY|"
                                r"CREDENTIALS?|BASIC_AUTH|PAT)$", re.I)
_ONE_WORD_CREDENTIAL = re.compile(r"(?i:password|passwd|passphrase|apikey|api_key)|TOKEN|SECRET")


def credential_name(name: str) -> bool:
    return bool(_CREDENTIAL_SUFFIX.search(name) or _ONE_WORD_CREDENTIAL.fullmatch(name))


MAX_SCRIPT = 400_000  # past this it's data, and nothing here is worth a slow hook


_XTRACE_ON = re.compile(r"^[ \t]*set[ \t][^\n#]*?(?:(?<=[ \t])-[a-zA-Z]*x[a-zA-Z]*\b|-o[ \t]+xtrace\b)|\A#![^\n]*\b(?:ba|z|k)?sh[ \t]+-[a-zA-Z]*x", re.M)
_XTRACE_OFF = re.compile(r"^[ \t]*set[ \t][^\n#]*?(?:\+[a-zA-Z]*x[a-zA-Z]*\b|\+o[ \t]+xtrace\b)", re.M)
_DEBUG_ONLY = re.compile(r"\b(?:DEBUG|TRACE|VERBOSE|XTRACE)\b", re.I)
_EXPANSION = re.compile(r"\$\{?([A-Za-z_]\w*)")
_ASSIGNMENT = re.compile(r"^[ \t]*(?:export[ \t]+|local[ \t]+|readonly[ \t]+|declare[ \t]+(?:-\w+[ \t]+)*)?([A-Za-z_]\w*)=")
_SINGLE_QUOTED = re.compile(r"'[^'\n]*'")
_COMMENT = re.compile(r"(?:^|[ \t])#.*$")


def _visible_lines(text: str) -> list[str]:
    """Each line with what the shell never expands taken out: single-quoted text, comments and heredoc bodies."""
    lines = text.split("\n")
    bodies = _heredoc_bodies(text)
    return ["" if number in bodies else _COMMENT.sub("", _SINGLE_QUOTED.sub("''", line)) for number, line in enumerate(lines, start=1)]


def traced_secrets(text: str, masked_by_runner: frozenset = frozenset()) -> Iterator[tuple[int, str]]:
    """(line, message) where set -x prints a credential. The shell prints each command after expansion, assignments included, so
    `: "${TOKEN:?}"` and `PASSWORD=$(...)` both put the value in the log. A CI runner that masks its secrets in logs, as GitHub does for
    `secrets.*`, names them in masked_by_runner, and those are left out. A value derived from one, such as a login token, isn't masked."""
    if len(text) > MAX_SCRIPT:
        return
    on = [match for match in _XTRACE_ON.finditer(text) if not _only_when_debugging(text, match.start())]
    if not on:
        return
    line_of = line_finder(text)
    offs = [line_of(match.start()) for match in _XTRACE_OFF.finditer(text)]
    lines = _visible_lines(text)
    reported = 0
    read_to = 0  # a second set -x inside a traced stretch adds nothing to read
    for start in on:
        first = line_of(start.start())
        last = offs[bisect.bisect_right(offs, first)] if bisect.bisect_right(offs, first) < len(offs) else len(lines) + 1
        for number in range(max(first + 1, read_to), last):
            name = _traced_credential(lines[number - 1], masked_by_runner)
            if name:
                yield number, f"set -x on line {first} prints this command with {name} written out, so the value lands in the log. Switch tracing off around it with set +x."
                reported += 1
                if reported >= MAX_PER_PATTERN:
                    return
        read_to = max(read_to, last)


def _only_when_debugging(text: str, offset: int) -> bool:
    """`[ -n "$DEBUG" ] && set -x`, set -x under an if on a debug flag, or under a --debug option: a person asked for the trace."""
    line_start = text.rfind("\n", 0, offset) + 1
    two_lines_up = text.rfind("\n", 0, max(0, text.rfind("\n", 0, max(0, line_start - 1)))) + 1
    return bool(_DEBUG_ONLY.search(text, two_lines_up, offset))


def _traced_credential(line: str, masked_by_runner: frozenset) -> str | None:
    assigned = _ASSIGNMENT.match(line)
    if assigned and credential_name(assigned.group(1)):
        return f"the value given to {assigned.group(1)}"
    for match in _EXPANSION.finditer(line):
        if credential_name(match.group(1)) and match.group(1) not in masked_by_runner and not line[max(0, match.start() - 1):match.start()] == "\\" and line[match.end():match.end() + 2] != ":+":
            return "$" + match.group(1)
    return None


# ---------------------------------------------------------------- retries around a write

_LOOP_WORD = re.compile(r"(?<![\w./$-])(for|while|until|do|done)(?![\w./-])")
_SLEEPS = re.compile(r"(?<![\w-])sleep(?![\w-])")
_LEAVES = re.compile(r"(?<![\w-])(?:break|exit[ \t]+0|return[ \t]+0)(?![\w-])")
_HTTP_TOOL = re.compile(r"(?<![\w./-])(curl|wget|gh[ \t]+api|https?)(?![\w./:-])")
_METHOD = re.compile(r"(?:-X|--request|--method)[ \t]*[= \t][ \t]*[\"']?([A-Za-z]+)")
_SENDS_DATA = {"curl": re.compile(r"(?:^|[ \t])(?:-d|--data(?:-raw|-binary|-urlencode|-ascii)?|-F|--form(?:-string)?|--json)(?=[ \t=]|$)"),
               "gh": re.compile(r"(?:^|[ \t])(?:-f|-F|--field|--raw-field|--input)(?=[ \t=]|$)")}  # curl's -f is --fail
_ASKS_GET = re.compile(r"(?:^|[ \t])(?:-G|--get)(?=[ \t]|$)")
_HTTPIE_METHOD = re.compile(r"^https?[ \t]+(?:--?[\w-]+(?:=\S+)?[ \t]+)*(POST|PATCH)\b")
_IDEMPOTENT_KEY = re.compile(r"idempoten", re.I)
_CURL_RETRY = re.compile(r"(?:^|[ \t])--retry(?:-all-errors)?(?:[ \t]+(?!0\b)\d+|(?=[ \t]|$))")
MAX_LOOP_HEAD = 300
MAX_COMMAND = 2000  # a method or data flag comes early in a command, and reading further per call would go quadratic on a long line


def _command_ends(text: str, masked: str) -> list[int]:
    """Where each command ends: a newline that isn't escaped, or ; | & outside quotes. Found once, so each call looks its end up."""
    return [match.start() for match in re.finditer(r"[;|&\n]", masked) if not (match.group(0) == "\n" and text[match.start() - 1:match.start()] == "\\")]


def _writes(raw: str, masked: str) -> str | None:
    """The method of an HTTP call that isn't safe to repeat: POST, said or implied by sending data, or PATCH. PUT and DELETE repeat harmlessly."""
    tool = _HTTP_TOOL.match(masked)
    if not tool:
        return None
    name = tool.group(1).split()[0]
    if name in ("http", "https"):  # HTTPie names the method as a word
        found = _HTTPIE_METHOD.match(raw)
        return found.group(1).upper() if found else None
    method = _METHOD.search(raw)
    if method:
        return method.group(1).upper() if method.group(1).upper() in ("POST", "PATCH") else None
    if name == "wget":
        return "POST" if re.search(r"--post-(?:data|file)", masked) else None
    return "POST" if _SENDS_DATA[name].search(masked) and not _ASKS_GET.search(masked) else None


def _loops(masked: str) -> Iterator[tuple[str, int, int]]:
    """(keyword, where the loop starts, where it ends), pairing each do with its done."""
    words = [(match.start(), match.group(1)) for match in _LOOP_WORD.finditer(masked)]
    heads = [(position, word) for position, word in words if word in ("for", "while", "until")]
    head_positions = [position for position, _ in heads]
    opened: list[int] = []
    for position, word in words:
        if word == "do":
            opened.append(position)
        elif word == "done" and opened:
            body = opened.pop()
            index = bisect.bisect_left(head_positions, body) - 1
            if index >= 0 and body - head_positions[index] <= MAX_LOOP_HEAD:
                yield heads[index][1], head_positions[index], position


def _any_between(positions: list[int], start: int, end: int) -> bool:
    index = bisect.bisect_left(positions, start)
    return index < len(positions) and positions[index] < end


def retried_writes(text: str) -> Iterator[tuple[int, str]]:
    """(line, message) for a POST or PATCH retried after a failure with no idempotency key. A timeout can come after the far side acted, so
    the retry does it twice. A loop that sleeps and stops on success is a retry, as is curl --retry. Each command is read once, and each loop
    asks sorted positions what it holds, so nested loops and long lines stay linear."""
    if len(text) > MAX_SCRIPT:
        return
    masked = mask(text)
    line_of = line_finder(text)
    ends = _command_ends(text, masked)
    writes: list[tuple[int, str]] = []  # (where, method) of each command that writes, by its first word
    retried: list[tuple[int, str, str]] = []
    read_until = -1
    for tool in _HTTP_TOOL.finditer(masked):
        if tool.start() < read_until:
            continue  # a later word of a command already read, such as a URL that says curl
        index = bisect.bisect_left(ends, tool.start())
        end = ends[index] if index < len(ends) else len(text)
        read_until = end
        raw, plain = text[tool.start():min(end, tool.start() + MAX_COMMAND)], masked[tool.start():min(end, tool.start() + MAX_COMMAND)]
        method = _writes(raw, plain)
        if method:
            writes.append((tool.start(), method))
            if tool.group(1) == "curl" and _CURL_RETRY.search(plain) and not _IDEMPOTENT_KEY.search(raw):
                retried.append((tool.start(), method, raw))
    if not writes:
        return
    write_positions = [where for where, _ in writes]
    sleeps = [match.start() for match in _SLEEPS.finditer(masked)]
    leaves = [match.start() for match in _LEAVES.finditer(masked)]
    keys = [match.start() for match in _IDEMPOTENT_KEY.finditer(text)]
    reported = 0
    seen: set[int] = set()
    for keyword, start, end in _loops(masked):
        index = bisect.bisect_left(write_positions, start)
        if index == len(writes) or writes[index][0] >= end or not _any_between(sleeps, start, end) or _any_between(keys, start, end):
            continue
        if not (_any_between(leaves, start, end) or keyword == "until" or re.match(r"while[ \t]+!", masked[start:start + 20])):
            continue
        where, method = writes[index]
        line = line_of(where)
        if line in seen:
            continue
        seen.add(line)
        yield line, (f"This {method} is retried by the loop on line {line_of(start)} after any failure, including a timeout after the far side acted, "
                     "so it can happen twice. Send an idempotency key the far side deduplicates on, or check whether the first one landed before retrying.")
        reported += 1
        if reported >= MAX_PER_PATTERN:
            return
    for where, method, _ in retried:
        line = line_of(where)
        if line not in seen:
            seen.add(line)
            yield line, f"curl --retry resends this {method} after a timeout, and the far side may already have acted on the first one. Send an idempotency key, or don't retry it."
            reported += 1
            if reported >= MAX_PER_PATTERN:
                return


# ---------------------------------------------------------------- credentials sent away

_STORE = (r"(?:~|\$\{?HOME\}?)/\.(?:aws/credentials|ssh/id_[\w.]+|netrc|npmrc|pypirc|docker/config\.json|kube/config|git-credentials|config/gh/hosts\.yml"
          r"|config/gcloud/(?:credentials\.db|application_default_credentials\.json|legacy_credentials))")
_READS_STORE = re.compile(rf"(?<![\w-])(?:cat|base64|tar|zip|gzip|xxd|cp|head|tail|openssl|sed|awk|grep)\b[^\n;|&]{{0,200}}?[\"']?{_STORE}|@[\"']?{_STORE}|<[ \t]*[\"']?{_STORE}")
_DUMPS_ENV = re.compile(r"(?:^|[|;&({]|\$\(|`)[ \t]*(?:env|printenv)[ \t]*(?=$|[|)`;&])", re.M)
_ENCODES = re.compile(r"(?<![\w-])(?:base64|gzip|xxd|openssl[ \t]+enc)(?![\w-])")
_SENDS = re.compile(r"(?<![\w./-])curl\b[^\n]{0,300}?(?:[ \t](?:-d|-F|-T)(?=[ \t=])|--data|--form|--upload-file|--json)|(?<![\w./-])wget\b[^\n]{0,300}?--post-(?:data|file)"
                    r"|/dev/(?:tcp|udp)/|(?<![\w./-])(?:nc|ncat|netcat)[ \t]+(?:-\w+[ \t]+)*[\w.-]+[ \t]+\d+")


def sent_credentials(text: str) -> Iterator[tuple[int, str]]:
    """(line, message) where a script reads a credential store, or dumps and encodes its whole environment, and also sends data off the machine.
    That's the shape of a malicious install or bootstrap script."""
    if len(text) > MAX_SCRIPT:
        return
    masked = mask(text)
    lines = _visible_lines(text)
    visible = "\n".join(lines)
    read = _READS_STORE.search(visible)
    dumped = _DUMPS_ENV.search(masked) if _ENCODES.search(masked) else None
    if not (read or dumped):
        return
    send = _SENDS.search(visible.replace("\\\n", "  "))  # same length, so offsets still count lines in visible
    if send:
        what = "a credential file" if read else "the whole environment"
        line_of = line_finder(visible)
        yield line_of(send.start()), f"This script reads {what} (line {line_of((read or dumped).start())}) and sends data to another host here."


# ---------------------------------------------------------------- a served file truncated in place

_WEB_ROOT = re.compile(r"^/(?:var/www|srv|usr/share/nginx|usr/share/caddy|usr/local/apache2/htdocs|var/lib/nginx)(?:/|$)|/(?:htdocs|public_html|wwwroot)(?:/|$)")
_REDIRECT = re.compile(r"(?<![<>&\d])>(?![>&(])[ \t]*|(?<![\w-])tee(?:[ \t]+-[^a\s][\w-]*)*[ \t]+(?!-a)")
_VALUE = re.compile(r"^[ \t]*(?:readonly[ \t]+|export[ \t]+|local[ \t]+|declare[ \t]+(?:-\w+[ \t]+)*)?([A-Za-z_]\w*)=(\"[^\"\n]*\"|'[^'\n]*'|[^\s;#]*)", re.M)
_REFERENCE = re.compile(r"\$\{?([A-Za-z_]\w*)(?::?-([^}]*))?\}?")
_LOOKS_TEMPORARY = re.compile(r"tmp|temp|\.new\b|\.part|\$\$|mktemp|XXXX|\.partial|\.swp|staging", re.I)
_MOVES_ONTO = re.compile(r"(?<![\w-])mv(?:[ \t]+-\w+)*[ \t]+\S+[ \t]+(\S+)")


def _target(text: str, start: int) -> str:
    if text[start:start + 1] in "\"'":
        close = text.find(text[start], start + 1, start + MAX_RESOLVED)
        return text[start + 1:close] if close > start else ""
    found = re.compile(r"[^\s;&|)<>]{1,1000}").match(text, start)
    return found.group(0) if found else ""


MAX_RESOLVED = 1000  # a path longer than this isn't one a web server serves, and the cap keeps `A="$A$A…"` from growing


class _Values:
    """The script's own assignments, each resolved once. A variable met again inside its own expansion stays as written, so `A="$A$A"`
    can't grow, and nothing grows past MAX_RESOLVED."""

    def __init__(self, raw: dict[str, str]) -> None:
        self.raw = raw
        self.done: dict[str, str] = {}

    def resolve(self, word: str, inside: frozenset = frozenset()) -> str:
        def value(match: re.Match) -> str:
            name = match.group(1)
            if name in inside or name not in self.raw:
                return match.group(2) if name not in self.raw and match.group(2) else match.group(0)
            if name not in self.done:
                self.done[name] = self.resolve(self.raw[name][:MAX_RESOLVED], inside | {name})[:MAX_RESOLVED]
            return self.done[name]
        return _REFERENCE.sub(value, word[:MAX_RESOLVED])[:MAX_RESOLVED]


def truncated_served_files(text: str) -> Iterator[tuple[int, str]]:
    """(line, message) where a script writes a file that a web server is serving with > or tee, which empties it before the new content arrives.
    Readers meanwhile get an empty or partial file, and a failed run leaves it that way."""
    if len(text) > MAX_SCRIPT or not re.search(r"/(?:var/www|srv|usr/share/nginx|usr/share/caddy|htdocs|public_html|wwwroot|usr/local/apache2|var/lib/nginx)\b", text):
        return
    masked = mask(text)
    values = _Values({name: value.strip("\"'") for name, value in _VALUE.findall(text)})
    moved_onto = {values.resolve(target.strip("\"'")) for target in islice(_MOVES_ONTO.finditer(text), 1000) for target in [target.group(1)]}
    bodies = _heredoc_bodies(text)
    line_of = line_finder(text)
    for match in islice(_REDIRECT.finditer(masked), 2000):
        line = line_of(match.start())
        if line in bodies:
            continue
        written = _target(text, match.end())
        path = values.resolve(written)
        if path and _WEB_ROOT.search(path) and not _LOOKS_TEMPORARY.search(written + path) and path not in moved_onto and "$" not in path:
            yield line, (f"This empties {path}, which a web server serves, before the new content is written, so readers get an empty or partial file and a "
                         "failed run leaves it that way. Write to a temporary file beside it and mv it into place.")
            return
