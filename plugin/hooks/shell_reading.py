"""Reading a shell command as a shell would: where each command ends, what its words are, and where it runs.

Best-effort, and not a security boundary. A static read can't see everything, so docs/failure-modes.md lists what gets past it. It
reads the command in order, so a `cd` only affects what comes after it, in its own subshell, and only if it certainly ran. When it isn't
sure, it assumes the project, because missing an edit is the worse mistake. A hook has seconds and a command can hold a large script or
data, so nothing here should grow faster than the command does.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
import shlex
from collections import defaultdict, deque
from collections.abc import Iterator
from typing import Callable, NamedTuple

from occam_commands import PYTHON, PYTHON_VALUE_FLAGS, head, run_by, unquote

MAX_ASSIGNMENTS = 50
MAX_DEPTH = 5
MAX_NESTED_QUOTES = 50
MAX_MISSING_DELIMITERS = 200
# A `$(` the reader can't close is usually invalid shell, but not always: an apostrophe in a comment inside one looks like a quote
# that never closes. So one isn't enough to stop matching, and a few bound the rescans.
UNCLOSED_TRIES = 8
MAX_GIT_CHARS = 4_000
OPERATORS = frozenset(";<>|&")
SPACES = frozenset(" \t\r\n\f")
BEFORE_A_COMMENT = frozenset(" \t;&|()\n")
BRANCH_OPENERS = {"if", "for", "while", "until", "case", "select"}
BRANCH_CLOSERS = {"fi", "done", "esac"}
HEREDOC = re.compile(r"""<<(-?)[ \t]*(?:"([^"\n]+)"|'([^'\n]+)'|\\?([\w.+-]+))""")
SHELL_RUNNERS = {"bash", "sh", "zsh", "dash", "ksh", "eval"}
FEEDERS = {"echo", "printf"}
CD_OPTIONS = {"-L", "-P", "-e", "-@", "--"}
DASH_C = re.compile(r"-[A-Za-z]*c")
DASH_M = re.compile(r"-[A-Za-z]*m")
ASSIGNMENT = re.compile(r"""(?:^|[\s;&|(])([A-Za-z_]\w*)=(?:"([^"'`()]*)"|'([^"']*)'|([^\s;&|()`"']+))(?=$|[\s;&|)])""")
MAY_NOT_STAY_PUT = re.compile(r"[\s;&|<>()]")


# ---------------------------------------------------------------- quotes and substitutions, the one place that reads them

def quote_end(text: str, start: int, depth: int = 0) -> int:
    """The index closing the quote or backtick opening at `start`, or -1. A double quote can hold `$(...)`, which can hold more quotes."""
    quote = text[start]
    if quote == "`" or (quote == "'" and text[start - 1:start] != "$"):
        return text.find(quote, start + 1)
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
        elif char == quote:
            return index
        elif quote == '"' and char == "$" and text[index + 1:index + 2] == "(" and depth < MAX_NESTED_QUOTES:
            end = substitution_end(text, index + 2, depth + 1)
            if end < 0:
                return -1
            index = end + 1
        else:
            index += 1
    return -1


def substitution_end(text: str, start: int, depth: int = 0) -> int:
    """The index of the `)` closing a `$(` whose contents begin at `start`, or -1."""
    level = 1
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char in "'\"`":
            end = quote_end(text, index, depth)
            if end < 0:
                return -1
            index = end + 1
            continue
        if char == "(":
            level += 1
        elif char == ")":
            level -= 1
            if not level:
                return index
        index += 1
    return -1


def substitutions(word: str) -> list[str]:
    """What this word runs when the shell expands it: `$(...)` and backticks, not inside single quotes and not escaped."""
    found: list[str] = []
    last_close = word.rfind("))")  # a search for `))` from past it finds nothing, so it isn't repeated at every `$((`
    index = 0
    while index < len(word):
        char = word[index]
        if char == "\\":
            index += 2
        elif char == "'" and word[index - 1:index] != "$":
            end = word.find("'", index + 1)
            index = end + 1 if end >= 0 else len(word)
        elif char == "`":
            end = word.find("`", index + 1)
            if end < 0:
                break
            found.append(word[index + 1:end])
            index = end + 1
        elif word.startswith("$((", index):  # arithmetic
            end = word.find("))", index) if last_close >= index else -1
            index = end + 2 if end >= 0 else index + 3
        elif word.startswith("$(", index):
            end = substitution_end(word, index + 2)
            if end < 0:
                break
            found.append(word[index + 2:end])
            index = end + 1
        else:
            index += 1
    return found


def _terminator(text: str, after: int, delimiter: str, tabs: bool) -> tuple[int, int] | None:
    match = re.compile(r"\n" + (r"\t*" if tabs else "") + re.escape(delimiter) + r"(?=\n|\Z)").search(text, after)
    return (match.start(), match.end()) if match else None


def split_heredocs(text: str) -> tuple[str, dict[str, deque]]:
    """The command without its heredoc bodies, and each body with whether the shell expands it, by delimiter, in order.

    Bodies start after the opener's line, one after another if a line opens several. A body with no terminating line stays where it is,
    since a `<<` that isn't really a heredoc is likelier than a shell reading to the end, and reading on sees more.
    """
    kept: list[str] = []
    bodies: dict[str, deque] = defaultdict(deque)
    missing: set[str] = set()  # searching again for one that wasn't there would be quadratic
    last_close = text.rfind("))")  # and so would searching for `))` from past the last one, at every `$((`
    pending: list[tuple[str, bool, bool]] = []
    previous = "\n"
    reading_quotes = True
    index = copied = 0
    while index < len(text):
        char = text[index]
        if char == "\n":
            previous = "\n"
            position = index
            for delimiter, tabs, expands in pending:
                ends = None
                if delimiter not in missing and len(missing) < MAX_MISSING_DELIMITERS:
                    ends = _terminator(text, position, delimiter, tabs)
                if not ends:
                    missing.add(delimiter)
                    break
                bodies[delimiter].append((text[position + 1:ends[0]] if ends[0] > position else "", expands))
                position = ends[1]
            pending = []
            if position > index:
                kept.append(text[copied:index])
                copied = index = position
                continue
            index += 1
        elif char == "\\":
            index += 2
            previous = "x"
        elif char in "'\"`" and reading_quotes:
            end = quote_end(text, index)
            if end < 0:
                reading_quotes = False  # not valid shell, and trying again from every later quote would be quadratic
                index += 1
            else:
                index = end + 1
            previous = "x"
        elif char == "#" and previous in BEFORE_A_COMMENT:
            newline = text.find("\n", index)
            index = newline if newline >= 0 else len(text)
        elif text.startswith("$((", index) and last_close >= index:  # `1<<4` isn't a heredoc
            index = text.find("))", index) + 2
            previous = "x"
        elif text.startswith("<<<", index):  # a here-string, whose word isn't a delimiter
            index += 3
            previous = "x"
        elif char == "<" and text.startswith("<<", index):
            match = HEREDOC.match(text, index)
            if match:
                delimiter = match.group(2) or match.group(3) or match.group(4)
                pending.append((delimiter, bool(match.group(1)), bool(match.group(4)) and "\\" not in match.group(0)))
                kept += [text[copied:index], f"<<{delimiter}" if delimiter.replace("-", "").replace(".", "").replace("+", "").isalnum() else match.group(0)]
                copied = index = match.end()
            else:
                index += 2
            previous = "x"
        else:
            previous = char
            index += 1
    kept.append(text[copied:])
    return "".join(kept), bodies


def without_heredoc_bodies(command: str) -> str:
    return split_heredocs(command)[0]


def expand_variables(command: str) -> str:
    """Resolve simple assignments, so `G=/usr/bin/git; $G reset --hard` still reads as git.

    Only whole values, set once. A variable set twice means different things at different points, so it stays a variable, as does one
    with a substitution or a quote inside, which can't be judged from here. A value that isn't a program stays one word where it lands,
    so `M="a; rm b"; echo $M` doesn't read as `rm`.
    """
    found = ASSIGNMENT.findall(command)
    if len(found) > MAX_ASSIGNMENTS:
        return command
    names = [name for name, *_ in found]
    for name, double_quoted, single_quoted, bare in found:
        if names.count(name) > 1:
            continue
        value = double_quoted or single_quoted or bare
        whole = shlex.quote(value) if MAY_NOT_STAY_PUT.search(value) else value
        reference = r"(?:\$" + re.escape(name) + r"\b|\$\{" + re.escape(name) + r"\})"  # not `${X:-default}`, which has more in it
        command = re.sub(r"(^|(?<=[;&|(\n]))([ \t]*)" + reference, lambda match: match.group(1) + match.group(2) + value, command)
        command = re.sub(reference, lambda _, replacement=whole: replacement, command)
    return command


def logical_lines(text: str) -> list[str]:
    """Split where a shell ends a command, which isn't every newline: quotes span lines and a backslash joins the next one.

    Splitting at each newline hid `pytest` in `pytest -q && git commit -m "a<newline>b"`. Comments go, because an apostrophe in one isn't
    a quote, and `# clean; rm -rf /` isn't a command. A quote that never closes isn't valid shell, so from that command on this falls back
    to every newline. Each `$(` that doesn't close rescans to the end, so after UNCLOSED_TRIES of them no later `$(` is matched, which
    keeps this linear. PowerShell's backslash isn't an escape, so a line ending in one there reads as joined, a known gap.
    """
    lines: list[str] = []
    current: list[str] = []
    previous = "\n"
    start = index = 0
    unclosed = 0
    last_brace = text.rfind("}")  # a search for `}` from past it finds nothing, so it isn't repeated at every `${`
    while index < len(text):
        char = text[index]
        if char == "\\":
            if text[index + 1:index + 2] != "\n":  # a joined line vanishes entirely: `a\<newline>#b` is one word
                current.append(text[index:index + 2])
                previous = "x"
            index += 2
        elif char in "'\"`":
            end = quote_end(text, index)
            if end < 0:
                return lines + text[start:].split("\n")
            current.append(text[index:end + 1])
            previous = "x"
            index = end + 1
        elif char == "$" and text[index + 1:index + 2] in ("(", "{"):
            if text[index + 1] == "(":
                end = substitution_end(text, index + 2) if unclosed < UNCLOSED_TRIES else -1
                unclosed += end < 0
            else:
                end = text.find("}", index) if last_brace >= index else -1
            if end < 0:
                current.append(char)
                previous = char
                index += 1
            else:
                current.append(text[index:end + 1])
                previous = "x"
                index = end + 1
        elif char == "#" and previous in BEFORE_A_COMMENT:
            newline = text.find("\n", index)
            index = newline if newline >= 0 else len(text)
        elif char == "\n":
            lines.append("".join(current))
            current = []
            previous = "\n"
            index += 1
            start = index
        else:
            current.append(char)
            previous = char
            index += 1
    return lines + ["".join(current)]


def shell_tokens(line: str) -> list[str]:
    """Words, operators and parentheses. A word keeps its quotes and substitutions whole, even mid-word as in `--message="a; b"`.

    A stray quote is an ordinary character, and so is each `$(` after UNCLOSED_TRIES that don't close, as in `logical_lines`.
    A parenthesis is always its own token, so `(>a` and `)>a` read as what they are.
    """
    tokens: list[str] = []
    word: list[str] = []
    reading_quotes = True
    unclosed = 0
    last_close, last_brace = line.rfind("))"), line.rfind("}")  # as in `substitutions` and `logical_lines`
    index = 0

    def finish_word() -> None:
        if word:
            tokens.append("".join(word))
            word.clear()

    while index < len(line):
        char = line[index]
        if char in SPACES:
            finish_word()
            index += 1
        elif char in "()":
            finish_word()
            arithmetic = line.find("))", index) if last_close >= index and line.startswith("((", index) else -1
            if arithmetic >= 0:  # `((a>b))` compares, and doesn't redirect
                tokens.append(line[index:arithmetic + 2])
                index = arithmetic + 2
            else:
                tokens.append(char)
                index += 1
        elif char in OPERATORS:
            finish_word()
            end = index
            while end < len(line) and line[end] in OPERATORS:
                end += 1
            tokens.append(line[index:end])
            index = end
        elif char == "\\":
            word.append(line[index:index + 2])
            index += 2
        elif char in "'\"`" and reading_quotes:
            end = quote_end(line, index)
            if end < 0:
                reading_quotes = False
                word.append(char)
                index += 1
            else:
                word.append(line[index:end + 1])
                index = end + 1
        elif char == "$" and line[index + 1:index + 2] in ("(", "{"):
            if line[index + 1] == "(":
                end = substitution_end(line, index + 2) if unclosed < UNCLOSED_TRIES else -1
                unclosed += end < 0
            else:
                end = line.find("}", index) if last_brace >= index else -1
            word.append(line[index:end + 1] if end >= 0 else char)
            index = end + 1 if end >= 0 else index + 1
        else:
            word.append(char)
            index += 1
    finish_word()
    return tokens


def is_operator(token: str) -> bool:
    return token in ("(", ")") or set(token) <= OPERATORS


def inline_code(words: list[str], stdin: str | None) -> str | None:
    """The Python this simple command runs from the command line, or None if it runs a script, a module or something else."""
    name, args = run_by(words)
    if not PYTHON.fullmatch(name):
        return None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("-", "/dev/stdin"):
            return stdin or ""
        if DASH_C.fullmatch(arg):
            code = args[index + 1] if index + 1 < len(args) else ""
            return code[2:-1].replace("\\n", "\n") if code.startswith("$'") and code.endswith("'") else code
        if arg in PYTHON_VALUE_FLAGS:
            index += 2
        elif DASH_M.fullmatch(arg) or not arg.startswith("-"):
            return None
        else:
            index += 1
    return stdin


class Step(NamedTuple):
    """One simple command, in the order the shell would reach it."""
    words: list[str]
    targets: list[str]  # where it redirects output
    elsewhere: bool  # a `cd` before it certainly left the project
    folder: str  # where a `cd` went, relative to where the command started, or absolute. "" if unknown or unmoved
    code: str | None  # the Python it runs from the command line, if it does


class _Reader:
    """Walks one command. A `(` starts a subshell, whose `cd` ends with it, and a `cd` that may not have run changes nothing.

    A `cd` to a place that may not exist only counts while its `&&` chain lasts, because after a `;` the next command runs either way.
    A temp folder this command made, or `$TMPDIR`, is taken as there. A `cd` inside the project is kept, since a read that wrongly stays
    in the folder only misnames a path that is still the project's.
    """

    def __init__(self, leaves: Callable[[str], bool], elsewhere: bool, folder: str, depth: int) -> None:
        self.leaves = leaves
        self.depth = depth
        self.steps: list[Step] = []
        self.places: list[tuple[bool, str]] = [(elsewhere, folder)]
        self.chain_start = self.places[0]
        self.outer: list[tuple[tuple[bool, str], bool, str]] = []
        self.fragile = False
        self.groups = 0  # inside if, for, a brace group or a function body, whether a `cd` runs or lasts can't be told
        self.before = ";"
        self.feed: str | None = None
        self.bodies: dict[str, deque] = {}

    def read(self, command: str) -> list[Step]:
        text, self.bodies = split_heredocs(command)
        for line in logical_lines(expand_variables(text)):
            self._read_line(shell_tokens(line))
        return self.steps

    def _read_line(self, tokens: list[str]) -> None:
        words: list[str] = []
        targets: list[str] = []
        stdin: str | None = None
        index = 0
        while index < len(tokens):
            token = tokens[index]
            following = tokens[index + 1] if index + 1 < len(tokens) else ""
            if not is_operator(token):
                self._read_substitutions(token)
                if token == "{" and (not words or words[0] == "function"):
                    self.groups += 1
                    words = []
                elif token == "}" and not words:
                    self.groups = max(0, self.groups - 1)
                else:
                    words.append(token)
                index += 1
            elif token in ("(", ")"):
                self._finish(words, targets, stdin, ";" if token == ")" else self.before)
                words, targets, stdin = [], [], None
                if token == "(":
                    self.outer.append((self.chain_start, self.fragile, self.before))
                    self.places.append(self.places[-1])
                    self.chain_start, self.fragile, self.before = self.places[-1], False, ";"
                elif len(self.places) > 1:  # a subshell's `cd` and chain end with it, and the outer chain carries on
                    self.places.pop()
                    self.chain_start, self.fragile, self.before = self.outer.pop()
                index += 1
            elif words[:1] == ["[["] and ("<" in token or ">" in token):
                words.append(token)  # compares inside `[[ a > b ]]`
                index += 1
            elif ">" in token:
                if words and words[-1].isdigit():
                    words.pop()  # `2>/dev/null rm x`: the 2 belongs to the redirect
                self._read_substitutions(following)
                if not (token.endswith("&") and following.isdigit()):
                    targets.append(unquote(following))
                index += 2
            elif token in ("<<", "<<-"):
                queue = self.bodies.get(unquote(following.lstrip("\\")))
                if queue:
                    body, expands = queue.popleft()
                    stdin = body
                    if expands:
                        self._read_substitutions('"' + body + '"' if '"' not in body else body)
                index += 2
            elif token == "<<<":
                self._read_substitutions(following)
                stdin = following[2:-1].replace("\\n", "\n") if following.startswith("$'") else unquote(following)
                index += 2
            elif "<" in token:
                self._read_substitutions(following)
                index += 2
            else:
                self._finish(words, targets, stdin, token)
                words, targets, stdin = [], [], None
                self.before = token
                index += 1
        if words or targets:
            self._finish(words, targets, stdin, ";")
        if not tokens or tokens[-1] not in ("&&", "||", "|"):
            self.before = ";"
            self._end_chain()

    def _read_substitutions(self, word: str) -> None:
        if self.depth >= MAX_DEPTH or ("$(" not in word and "`" not in word):
            return
        elsewhere, folder = self.places[-1]
        for inner in substitutions(word):
            self.steps += _Reader(self.leaves, elsewhere, folder, self.depth + 1).read(inner)

    def _end_chain(self) -> None:
        if self.fragile:
            self.places[-1] = self.chain_start
            self.fragile = False
        self.chain_start = self.places[-1]

    def _finish(self, words: list[str], targets: list[str], stdin: str | None, after: str) -> None:
        if not words and not targets:  # after a `)`, which can still end a chain
            if after == ";":
                self._end_chain()
            elif after == "&":
                self.places[-1], self.fragile = self.chain_start, False
            return
        given = stdin if stdin is not None else (self.feed if self.before == "|" else None)
        elsewhere, folder = self.places[-1]
        self.steps.append(Step(words, targets, elsewhere, folder, inline_code(words, given) if words else None))
        first = next((word for word in words if not re.match(r"^\w+=", word)), "")
        program = os.path.basename(unquote(first)).lstrip("\\")
        if program in BRANCH_OPENERS:
            self.groups += 1
        elif program in BRANCH_CLOSERS:
            self.groups = max(0, self.groups - 1)
        name, args = head(words)
        if program in ("cd", "pushd") and name == program and not self.groups and self.before in (";", "&&") and after not in ("|", "&", "||"):
            self._move(next((arg for arg in args if arg not in CD_OPTIONS), ""))
            self.fragile = self.fragile or self.before == "&&"  # `x && cd y` may not have run, so what follows the chain can't assume it
        elif program == "popd":
            self.places[-1] = (False, "")
            self.fragile = False
        self.feed = stdin if stdin is not None else " ".join(args) if name in FEEDERS else None
        if self.depth < MAX_DEPTH:
            self._read_nested(name, args, given)
        if after == "&":  # that chain ran in the background, so its `cd` never touched what follows
            self.places[-1] = self.chain_start
            self.fragile = False
        elif after == ";":
            self._end_chain()

    def _move(self, place: str) -> None:
        elsewhere, folder = self.places[-1]
        place = home_expanded(place)
        if not place:
            return
        if place == "-":  # can lead straight back, so nothing after it can be ruled out
            self.places[-1] = (False, "")
            self.fragile = False
        elif place.startswith("$") or "$(" in place or "`" in place:
            self.places[-1] = (True, "") if self.leaves(place) else (False, "")
        elif elsewhere and not folder and not os.path.isabs(place):
            pass  # somewhere under a temp folder this can't name
        else:
            where = os.path.normpath(os.path.join(folder, os.path.expanduser(place)))
            if self.leaves(where):
                self.places[-1] = (True, where)
                self.fragile = True  # it may not exist, and then the next command after a `;` runs here
            else:
                self.places[-1] = (False, "" if where == "." else where)
                self.fragile = False

    def _read_nested(self, name: str, args: list[str], stdin: str | None) -> None:
        if name not in SHELL_RUNNERS:
            return
        inner = " ".join(args) if name == "eval" else None
        if name != "eval":
            for index, arg in enumerate(args):
                if DASH_C.fullmatch(arg):
                    inner = args[index + 1] if index + 1 < len(args) else ""
                    break
                if not arg.startswith("-") and arg not in ("+x", "+e"):
                    break  # a script, which runs what it holds and can't be read from here
            else:
                inner = stdin
        if inner:
            elsewhere, folder = self.places[-1]
            self.steps += _Reader(self.leaves, elsewhere, folder, self.depth + 1).read(inner.replace('\\"', '"'))


def home_expanded(word: str) -> str:
    """`$HOME` as the folder it names. A project usually lives inside it, so a path under it is judged by where it is, not taken as scratch."""
    return re.sub(r"^\$(?:HOME(?!\w)|\{HOME\})", lambda _: os.path.expanduser("~"), word)


def _stays(_: str) -> bool:
    return False


_READ: dict[str, list[Step]] = {}  # one hook reads the same command several ways, and a read can take a second on a huge one
MAX_REMEMBERED = 4


def read_steps(command: str, leaves: Callable[[str], bool] = _stays) -> list[Step]:
    """The steps, remembered for the few commands one hook call reads, when no `cd` needs judging. Callers only read the list."""
    if leaves is not _stays:
        return _Reader(leaves, False, "", 0).read(command)
    if command not in _READ:
        if len(_READ) >= MAX_REMEMBERED:
            _READ.clear()
        _READ[command] = _Reader(leaves, False, "", 0).read(command)
    return _READ[command]


def parse_shell(command: str) -> tuple[list[list[str]], list[str]]:
    """Split a command line into its simple commands and its redirect targets. Best-effort."""
    steps = read_steps(command)
    return [step.words for step in steps if step.words], [target for step in steps for target in step.targets]


class Stage(NamedTuple):
    """One command in a pipeline, with its words as written, so a word holding `$(...)` keeps it."""
    words: list[str]
    fed: str | None  # the word a here-string `<<<` feeds it
    saved: bool  # its output goes to a file, not on to the next stage or the terminal


PIPE_SEPARATORS = {"|", "|&"}


def pipelines(command: str) -> list[list[Stage]]:
    """The pipelines at the top level, stage by stage, so what reaches the terminal can be told from what is piped on, saved or captured.

    A subshell's parentheses end a pipeline here, and what a substitution runs is left in its word for the caller to read.
    """
    found: list[list[Stage]] = []
    text, _ = split_heredocs(command)
    for line in logical_lines(expand_variables(text)):
        found += _line_pipelines(shell_tokens(line))
    return found


def _line_pipelines(tokens: list[str]) -> list[list[Stage]]:
    found: list[list[Stage]] = []
    stages: list[Stage] = []
    for segment, separator in _segments(tokens):
        stage = _stage(segment)
        if stage is not None:
            stages.append(stage)
        if separator not in PIPE_SEPARATORS and stages:  # the end of the line ends a pipeline too
            found.append(stages)
            stages = []
    return found


def _segments(tokens: list[str]) -> Iterator[tuple[list[str], str]]:
    """The tokens of each stage, and the operator that ends it, or "" at the end. A redirect keeps the word after it, whatever that is."""
    segment: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if is_operator(token) and _ends_a_stage(token):
            yield segment, token
            segment, index = [], index + 1
        elif is_operator(token):
            segment += tokens[index:index + 2]
            index += 2
        else:
            segment.append(token)
            index += 1
    yield segment, ""


def _ends_a_stage(operator: str) -> bool:
    return operator != "<<<" and not (">" in operator and operator not in ("(", ")")) and "<" not in operator


def _stage(segment: list[str]) -> Stage | None:
    """A stage from its tokens: its words, what a here-string feeds it, and whether its output is saved. None when it has neither."""
    words: list[str] = []
    fed: str | None = None
    saved = False
    index = 0
    while index < len(segment):
        token = segment[index]
        following = segment[index + 1] if index + 1 < len(segment) else ""
        if not is_operator(token):
            words.append(token)
            index += 1
            continue
        if token == "<<<":
            fed = following
        elif ">" in token and _saves_output(token, following, words):
            saved = True
        index += 2
    return Stage(words, fed, saved) if words or fed is not None else None


def _saves_output(operator: str, following: str, words: list[str]) -> bool:
    """Does this redirect send the output to a file? `2>` sends only errors, and `>&2` sends output to them. Takes the descriptor before it,
    as `2` in `2>`, off `words`."""
    descriptor = words.pop() if words and words[-1].isdigit() else "1"
    return operator.startswith("&") or (descriptor == "1" and not (operator.endswith("&") and following.isdigit()))


def git_commands(command: str) -> list[str]:
    """Each git invocation as `git ...`, from the words that really run it. Quoted text is out of it, so a message can't read as an operation."""
    found = []
    for step in read_steps(command):
        for index, word in enumerate(step.words):
            if os.path.basename(re.sub(r"""\$?['"]""", "", word)).lstrip("\\") == "git":
                arguments = [unquote(rest) if unquote(rest).startswith("-") else "Q" if rest[:1] in "'\"" else rest for rest in step.words[index + 1:]]
                found.append("git " + " ".join(arguments)[:MAX_GIT_CHARS])
                break
    return found
