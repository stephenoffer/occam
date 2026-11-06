"""What goes wrong in shell scripts, for hosts where shellcheck isn't installed. shellcheck outranks these wherever it's available.

Rules read a mask of the script with quoted text, comments and heredoc bodies blanked, so `$var` still visible in it really is unquoted.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterable

from .source import Source

OUTGROWN_LINES = 300  # occam-shell says about a hundred lines is when to ask. This is when it's plainly past that
MAX_LINE_READ = 2000  # past this a line is data, and several rules would otherwise take quadratic time on one
_POSIX_INTERPRETER = re.compile(r"^#!\s*(?:/usr)?/bin/(?:env\s+)?(?:sh|dash|ash)\b")
_NOT_BASH = re.compile(r"^#![^\n]*\b(?:zsh|fish|csh|tcsh|ksh)\b")
_STRICT = re.compile(r"^[ \t]*set\s+-[a-zA-Z]*e|^[ \t]*set\s+-o\s+errexit", re.M)
_COMMAND_START = re.compile(r"(?:^|[;&|(]|\bthen\b|\bdo\b|\belse\b)[ \t]*(?:sudo[ \t]+)?")
_VARIABLE = r"\$(?:\{[A-Za-z_@*0-9]\w*\}|[A-Za-z_@*0-9]\w*)"
_PATH_COMMAND = re.compile(_COMMAND_START.pattern + r"(cp|mv|cat|cd|mkdir|rmdir|touch|chmod|chown|ln|tar|source|rm)[ \t]([^;&|\n]*)", re.M)
_BARE_VARIABLE = re.compile(rf"(?<![\w\"'=]){_VARIABLE}")
_CD = re.compile(_COMMAND_START.pattern + r"cd(?:[ \t]+[^;&|\n]*)?[ \t]*(;|$|\n)", re.M)
_LS_PARSE = re.compile(r"\bfor\s+\w+\s+in\s+[^;\n]*(?:\$\(|`)\s*ls\b|(?:^|[;&(]|\$\(|`)[ \t]*ls\b[^|\n;]*\|\s*(?:while\b|xargs\b|grep\b|awk\b|sed\b|head\b|tail\b)", re.M)
_WORD_SPLIT = re.compile(r"\bfor\s+\w+\s+in\s+[^;\n]*(?:\$\(|`)\s*(?:find|git\s+ls-files|grep|cat|locate)\b|(?:^|[;&|]\s*)(?:rm|cp|mv|wc|cat|chmod|chown|ls)\b[^\n;|]*(?<!\")(?:\$\(|`)\s*(?:find|git\s+ls-files|locate)\b", re.M)
_MASKED = re.compile(r"^[ \t]*(?:local|export|readonly|declare|typeset)(?:[ \t]+-\w+)*[ \t]+\w+=[\"']?\$\((?!\()", re.M)  # $(( is arithmetic, which can't fail this way
_RM_VARIABLE = re.compile(r"(?:^|[;&|(]|\bthen\b|\bdo\b)[ \t]*(?:sudo[ \t]+)?rm[ \t]+-[a-zA-Z]*[rR][a-zA-Z]*[ \t]+(?:--[ \t]+)?\"?\$(?:\{(\w+)\}|(\w+))\"?(/\S*)", re.M)
_RM_SAFE_VARIABLES = {"HOME", "PWD", "TMPDIR", "BASH_SOURCE"}
_PREDICTABLE_TMP = re.compile(r"/tmp/[\w.-]*\$\$|>>?[ \t]*\"?/tmp/\w")
_COMMENT_BEFORE = re.compile(r"(?:^|\s)#")
_EVAL = re.compile(r"(?:^|[;&|(]|\bthen\b)[ \t]*eval[ \t]+\S", re.M)
_NONPORTABLE = (
    ("sed -i", re.compile(r"\bsed\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*i\b"), "sed -i takes different arguments on GNU and BSD, so a script using it works on only one"),
    ("grep -P", re.compile(r"\bgrep\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*P\b"), "grep -P doesn't exist on BSD or macOS"),
    ("readlink -f", re.compile(r"\breadlink\s+-[a-zA-Z]*f\b"), "readlink -f isn't on older macOS"),
    ("date -d", re.compile(r"\bdate\s+(?:-[a-zA-Z]+\s+)*-d\b"), "date -d is GNU only, and BSD uses -j -f"),
    ("date -j", re.compile(r"\bdate\s+(?:-[a-zA-Z]+\s+)*-j\b"), "date -j is BSD only"),
    ("stat -c", re.compile(r"\bstat\s+(?:-[a-zA-Z]+\s+)*-c\b"), "stat -c is GNU only, and BSD uses -f"),
    ("stat -f", re.compile(r"\bstat\s+(?:-[a-zA-Z]+\s+)*-f\b"), "stat -f means something else on GNU"),
    ("xargs -r", re.compile(r"\bxargs\s+(?:-[a-zA-Z0-9]+\s+)*-[a-zA-Z]*r\b"), "xargs -r isn't on older BSD and macOS"),
    ("find -printf", re.compile(r"\bfind\b[^|;\n]*\s-printf\b"), "find -printf is GNU only"),
    ("base64 -w", re.compile(r"\bbase64\s+(?:-[a-zA-Z]+\s+)*-w\b"), "base64 -w is GNU only"),
    ("timeout", re.compile(r"(?:^|[;&|(]|\bthen\b|\bdo\b)[ \t]*timeout[ \t]+\d", re.M), "timeout isn't on macOS"),
    ("nproc", re.compile(r"(?:^|[\s(`])nproc\b"), "nproc isn't on macOS"),
    ("tac", re.compile(r"(?:^|[|;&(]\s*)tac\b"), "tac isn't on macOS"),
)
_CHECKS_PLATFORM = re.compile(r"\buname\b|\$\{?OSTYPE\b")
_BASHISMS = (
    ("[[", re.compile(r"(?:^|[\s;&|(])\[\[\s"), "`[[`"),
    ("array", re.compile(r"(?:^|[\s;&(])\w+=\("), "an array"),
    ("function keyword", re.compile(r"(?:^|[;&])\s*function\s+[\w:.-]+"), "the `function` keyword"),
    ("<<<", re.compile(r"<<<"), "a here-string"),
    ("&>", re.compile(r"&>"), "`&>`"),
    ("process substitution", re.compile(r"[<>]\("), "process substitution"),
    ("source", re.compile(r"(?:^|[;&|])[ \t]*source[ \t]+\S", re.M), "`source`"),
    ("declare", re.compile(r"(?:^|[;&|])[ \t]*(?:declare|typeset)[ \t]", re.M), "`declare`"),
    ("substring", re.compile(r"\$\{\w+(?:/{1,2}|:[-0-9 ]*\d)"), "bash parameter expansion"),
    ("bash variable", re.compile(r"\$\{?(?:BASH_SOURCE|BASHPID|PIPESTATUS|FUNCNAME)\b"), "a bash-only variable"),
)
_ARITHMETIC = re.compile(r"\$?\(\([^\n]*?\)\)")
_HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\?([\w.-]+))")
_BASH_ERROR = re.compile(r"line (\d+): (.*)")
_LEAVES_THE_SHELL = re.compile(r"^(?:exit|exec)\b", re.M)  # what follows may be a Perl program or an archive, so a parse error past it means nothing
_BASH_VERSION = re.compile(r"version (\d+)\.(\d+)")


def _skip_heredocs(text: str, start: int, pending: list[tuple[str, bool]]) -> int:
    """Past the bodies of the heredocs opened on the line that just ended, leaving them blank is the caller's job."""
    position = start
    for delimiter, strip_tabs in pending:
        while position < len(text):
            end = text.find("\n", position)
            end = len(text) if end < 0 else end
            line = text[position:end]
            position = end + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
    return min(position, len(text))


def mask(text: str) -> str:
    """The script with everything that isn't command text blanked: quoted text, comments, heredoc bodies. Offsets and newlines stay where they were."""
    out = list(text)

    def blank(start: int, end: int) -> None:
        for index in range(start, min(end, len(text))):
            if text[index] != "\n":
                out[index] = " "

    index = 0
    pending: list[tuple[str, bool]] = []
    while index < len(text):
        character = text[index]
        if character == "\\":
            blank(index, index + 2)
            index += 2
        elif character == "'":
            close = text.find("'", index + 1)
            close = len(text) if close < 0 else close
            blank(index + 1, close)
            index = close + 1
        elif character == '"':
            close = index + 1
            while close < len(text) and text[close] != '"':
                close += 2 if text[close] == "\\" else 1
            blank(index + 1, close)
            index = close + 1
        elif character == "#" and (index == 0 or text[index - 1] in " \t\n;&|("):
            close = text.find("\n", index)
            close = len(text) if close < 0 else close
            blank(index, close)
            index = close
        elif text.startswith("<<<", index):
            index += 3
        elif (character == "(" or text.startswith("$(", index)) and text.startswith("((", index + (character == "$")):
            arithmetic = _ARITHMETIC.match(text, index)  # 1<<2 here is a shift, and taking it for a heredoc would blank the rest of the script
            index = arithmetic.end() if arithmetic else index + 2
        elif text.startswith("<<", index):
            heredoc = _HEREDOC.match(text, index)
            if heredoc:
                pending.append((heredoc.group(2) or heredoc.group(3) or heredoc.group(4), bool(heredoc.group(1))))
                index = heredoc.end()
            else:
                index += 2
        elif character == "\n" and pending:
            after = _skip_heredocs(text, index + 1, pending)
            blank(index + 1, after)
            pending = []
            index = after
        else:
            index += 1
    return "".join(out)


def outside_heredocs(text: str, raw: list[tuple]) -> list[tuple]:
    """Text rules see a heredoc as commands, and it's only data. A credential in one is still a credential."""
    masked = mask(text).split("\n")
    lines = text.split("\n")
    inside = {number for number, line in enumerate(lines, start=1) if line.strip() and not masked[number - 1].strip()}
    opened = _heredoc_bodies(text)
    return [item for item in raw if item[0] == "hardcoded-secret" or item[1] not in (inside & opened)]


def _heredoc_bodies(text: str) -> set[int]:
    bodies: set[int] = set()
    lines = text.split("\n")
    number = 0
    while number < len(lines):
        delimiters = _HEREDOC.findall(_ARITHMETIC.sub("", lines[number])) if "<<" in lines[number] else []
        number += 1
        for dash, single, double, bare in delimiters:
            delimiter = single or double or bare
            while number < len(lines):
                line = lines[number].lstrip("\t") if dash else lines[number]
                number += 1
                if line == delimiter:
                    break
                bodies.add(number)
    return bodies


def _bash_says(text: str) -> tuple[int, str, bool] | None:
    """(line, message, whether this bash is older than version 4) if bash can't parse this. -n reads without running, and extglob because a script can switch it on."""
    bash = shutil.which("bash")
    if not bash:
        return None
    environment = {key: value for key, value in os.environ.items() if key not in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS")}
    try:
        done = subprocess.run([bash, "--noprofile", "--norc", "-O", "extglob", "-n"], input=text, capture_output=True, text=True, errors="replace", timeout=5, env=environment)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 0:
        return None
    match = _BASH_ERROR.search(done.stderr)
    if not match:
        return None
    try:
        version = subprocess.run([bash, "--version"], capture_output=True, text=True, errors="replace", timeout=5, env=environment).stdout
    except (OSError, subprocess.SubprocessError):
        version = ""
    found = _BASH_VERSION.search(version)
    return int(match.group(1)), match.group(2)[:120], bool(found and int(found.group(1)) < 4)


def _line(offsets: Source, position: int) -> int:
    return offsets.line_of(position)


def line_of_text(source: Source, number: int) -> str:
    starts = source.line_starts
    end = starts[number] - 1 if number < len(starts) else len(source.text)
    return source.text[starts[number - 1]:end]


def _syntax(source: Source) -> Iterable[tuple]:
    if _NOT_BASH.match(source.text) or source.path.endswith(".zsh"):
        return
    said = _bash_says(source.text)
    if said:
        line, message, old = said
        first_exit = _LEAVES_THE_SHELL.search(source.text)
        if first_exit and source.line_of(first_exit.start()) < line:
            return
        note = " This bash is older than 4, so newer syntax may be the cause." if old else ""
        yield "shell-syntax", line, f"bash can't parse this: {message}.{note}", {"confidence": "medium"} if old else {}


def _quoting(source: Source, masked: str) -> Iterable[tuple]:
    seen = set()
    for match in _PATH_COMMAND.finditer(masked):
        command, rest = match.group(1), match.group(2)
        variable = _BARE_VARIABLE.search(rest)
        if not variable:
            continue
        if command == "rm" and re.match(r"-[a-zA-Z]*[rf]", rest.strip()):
            continue  # shell-unquoted-rm reports this one
        line = _line(source, match.start(2) + variable.start())
        if line not in seen and len(seen) < 10:
            seen.add(line)
            yield "shell-unquoted-path", line, f"{command} gets {variable.group(0)} unquoted, so spaces or a glob in the value change what it touches.", {}


def _flow(source: Source, masked: str, strict: bool) -> Iterable[tuple]:
    if not strict:
        reported = 0
        for match in _CD.finditer(masked):
            line = _line(source, match.start() + len(match.group(0)) - len(match.group(0).lstrip()))
            if reported < 5 and not line_of_text(source, line).rstrip().endswith("\\"):  # continues with && on the next line
                reported += 1
                yield "shell-cd-unchecked", line, None, {}
    for match in _MASKED.finditer(source.text):
        if not masked[match.start():match.end()].isspace():
            yield "shell-masked-failure", _line(source, match.start()), None, {}
    evals = [match for match in _EVAL.finditer(masked) if "$" in line_of_text(source, _line(source, match.start()))]
    for match in evals[:5]:
        yield "dynamic-eval", _line(source, match.start()), "eval runs what a variable holds.", {}


def _listing(source: Source, masked: str) -> Iterable[tuple]:
    for match in list(_LS_PARSE.finditer(masked))[:5]:
        yield "shell-ls-parse", _line(source, match.end() - 1), None, {}
    for match in list(_WORD_SPLIT.finditer(masked))[:5]:
        yield "shell-word-split", _line(source, match.end() - 1), None, {}


def _removal(source: Source, masked: str) -> Iterable[tuple]:
    # Quoted variables are what this rule is about, so it reads the raw text and only asks the mask whether the command itself is real.
    for match in _RM_VARIABLE.finditer(source.text):
        name = match.group(1) or match.group(2)
        start = source.text.index("rm", match.start())
        if name in _RM_SAFE_VARIABLES or masked[start] == " ":
            continue
        everything = match.group(3).rstrip('"').startswith("/*")
        yield "shell-rm-unguarded", _line(source, start), f"If {name} is empty this removes {'everything under /' if everything else 'a path under /'}.", {} if everything else {"severity": "medium"}


def _temp(source: Source, masked: str) -> Iterable[tuple]:
    bodies = _heredoc_bodies(source.text)
    for match in _PREDICTABLE_TMP.finditer(source.text):  # the raw text, because a quoted path is just as predictable
        line = _line(source, match.start())
        before = source.text[source.line_starts[line - 1]:match.start()]
        if line not in bodies and not _COMMENT_BEFORE.search(before):
            yield "insecure-tempfile", line, "A predictable path in /tmp can be planted by another user.", {}
            break
    if re.search(r"\bmktemp\b", masked) and not re.search(r"^[ \t]*trap\b", masked, re.M):
        yield "shell-tmp-no-trap", _line(source, re.search(r"\bmktemp\b", masked).start()), None, {}


def _portability(source: Source, masked: str) -> Iterable[tuple]:
    guarded = {"confidence": "low"} if _CHECKS_PLATFORM.search(source.text) else {}
    for _, pattern, message in _NONPORTABLE:
        match = pattern.search(masked)
        if match:
            yield "shell-nonportable", _line(source, match.start() + len(match.group(0)) - len(match.group(0).lstrip())), f"{message}.", guarded


def _bashisms(source: Source, masked: str) -> Iterable[tuple]:
    if not _POSIX_INTERPRETER.match(source.text):
        return
    for _, pattern, label in _BASHISMS:
        match = pattern.search(masked)
        if match:
            yield "shell-bashism", _line(source, match.start() + len(match.group(0)) - len(match.group(0).lstrip())), f"{label} isn't POSIX, and this script's shebang asks for sh, which is dash on Debian and Ubuntu.", {}


def shell_findings(source: Source) -> Iterable[tuple]:
    """Each rule family in turn. Findings carry (rule, line, message, overrides), as the text rules do."""
    masked = "\n".join(" " * len(line) if len(line) > MAX_LINE_READ else line for line in mask(source.text).split("\n"))
    strict = bool(_STRICT.search(masked))
    yield from _syntax(source)
    yield from _quoting(source, masked)
    yield from _flow(source, masked, strict)
    yield from _listing(source, masked)
    yield from _removal(source, masked)
    yield from _temp(source, masked)
    yield from _portability(source, masked)
    yield from _bashisms(source, masked)
    if sum(1 for line in masked.split("\n") if line.strip()) > OUTGROWN_LINES:
        yield "shell-outgrown", 1, None, {}
