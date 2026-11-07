"""Reading a shell command as a shell would: where each command ends, what its words are, and where it runs.

Best-effort, and not a security boundary. A static read can't see everything, so docs/failure-modes.md lists what gets past it. It
reads the command in order, so a `cd` only affects what comes after it, in its own subshell, and only if it certainly ran. When it isn't
sure, it assumes the project, because missing an edit is the worse mistake. A hook has seconds and a command can hold a large script or
data, so nothing here should grow faster than the command does.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import ast
import os
import re
import shlex
from collections import defaultdict, deque
from typing import Callable, NamedTuple

from occam_commands import PYTHON, PYTHON_VALUE_FLAGS, head, run_by, unquote

MAX_ASSIGNMENTS = 50
MAX_DEPTH = 5
MAX_NESTED_QUOTES = 50
MAX_MISSING_DELIMITERS = 200
MAX_GIT_CHARS = 4_000
MAX_PYTHON_CHARS = 100_000  # Python 3.9's parser segfaults on deep expressions from about 210,000 characters, and no `except` catches that.
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
LOOKS_LIKE_A_WRITE = re.compile(r"\bopen\(|\.write_(?:text|bytes)\(|\b(?:remove|unlink|rmtree|rename|move)\(")
MODE = re.compile(r"[rwaxbtU+]+")
WRITE_MODE = frozenset("wax+")
PATH_ONLY_METHODS = {"write_text", "write_bytes", "unlink", "rmdir", "touch"}
# Which arguments name something this changes.
FILE_FUNCTIONS = {"os.remove": (0,), "os.unlink": (0,), "os.rename": (0, 1), "os.replace": (0, 1), "os.rmdir": (0,), "os.removedirs": (0,), "os.truncate": (0,),
                  "shutil.rmtree": (0,), "shutil.move": (0, 1), "shutil.copy": (1,), "shutil.copy2": (1,), "shutil.copyfile": (1,), "shutil.copytree": (1,)}
MODULE_OPENERS = {"gzip", "bz2", "lzma", "io", "codecs", "tarfile", "builtins"}
RUNS_A_COMMAND = {"os.system", "subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.Popen"}
COMMANDS_THAT_CHANGE_FILES = {"rm", "mv", "cp", "sed", "tee", "truncate", "unlink", "touch", "rmdir", "dd", "ln", "install", "perl"}
TEMP_MAKERS = {"mkdtemp", "mkstemp", "gettempdir", "TemporaryDirectory", "NamedTemporaryFile", "TemporaryFile"}


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
            end = word.find("))", index)
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
        elif text.startswith("$((", index) and text.find("))", index) >= 0:  # `1<<4` isn't a heredoc
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
    to every newline. PowerShell's backslash isn't an escape, so a line ending in one there reads as joined, a known gap.
    """
    lines: list[str] = []
    current: list[str] = []
    previous = "\n"
    start = index = 0
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
            end = substitution_end(text, index + 2) if text[index + 1] == "(" else text.find("}", index)
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

    A stray quote is an ordinary character. A parenthesis is always its own token, so `(>a` and `)>a` read as what they are.
    """
    tokens: list[str] = []
    word: list[str] = []
    reading_quotes = True
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
            arithmetic = line.find("))", index) if line.startswith("((", index) else -1
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
            end = substitution_end(line, index + 2) if line[index + 1] == "(" else line.find("}", index)
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


def read_steps(command: str, leaves: Callable[[str], bool] = lambda _: False) -> list[Step]:
    return _Reader(leaves, False, "", 0).read(command)


def parse_shell(command: str) -> tuple[list[list[str]], list[str]]:
    """Split a command line into its simple commands and its redirect targets. Best-effort."""
    steps = read_steps(command)
    return [step.words for step in steps if step.words], [target for step in steps for target in step.targets]


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


# ---------------------------------------------------------------- what inline Python writes

def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else ""
    return ""


class _PythonPaths:
    """Resolves an expression to the paths it can only be, from constants, single assignments and a helper's literal arguments."""

    def __init__(self, tree: ast.AST) -> None:
        self.assigned: dict[str, list] = defaultdict(list)
        self.parameters: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.calls: dict[str, list[ast.Call]] = defaultdict(list)
        self.aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._bind(target, node.value)
            elif isinstance(node, (ast.AugAssign, ast.For, ast.comprehension, ast.NamedExpr)):
                self._bind(node.target, None)
            elif isinstance(node, ast.withitem) and node.optional_vars:
                self._bind(node.optional_vars, node.context_expr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for position, argument in enumerate(node.args.args):
                    self.parameters[argument.arg].append((node.name, position))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.calls[node.func.id].append(node)
            elif isinstance(node, ast.Import):
                self.aliases.update({alias.asname: alias.name for alias in node.names if alias.asname})
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.aliases.update({alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names})

    def _bind(self, target: ast.AST, value: ast.AST | None) -> None:
        if isinstance(target, ast.Name):
            self.assigned[target.id].append(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind(item, None)

    def name_of(self, node: ast.AST) -> str:
        """The dotted name, past `import os as o` and `from os import remove`."""
        name = _dotted(node)
        first, _, rest = name.partition(".")
        real = self.aliases.get(first, first)
        return f"{real}.{rest}" if rest else real

    def resolve(self, node: ast.AST | None, depth: int = 0) -> list[str] | None:
        if node is None or depth > 8:
            return None
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else None
        if isinstance(node, ast.Name):
            return self._resolve_name(node.id, depth)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self._joined([node.left, node.right], depth)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.resolve(node.left, depth + 1)
            right = self.resolve(node.right, depth + 1)
            return [one + two for one in left for two in right] if left and right else left if left and os.path.isabs(left[0]) else None
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant) and os.path.isabs(str(node.values[0].value)):
            return [str(node.values[0].value)]  # only where it starts, which settles whether it's the project's
        if isinstance(node, ast.Call):
            name = self.name_of(node.func)
            last = name.rsplit(".", 1)[-1]
            if last in TEMP_MAKERS:
                return ["$TMPDIR/x"]
            if last in ("Path", "PurePath") and node.args:
                return self._joined(node.args, depth)
            if last in ("str", "fspath", "abspath", "realpath") and node.args:
                return self.resolve(node.args[0], depth + 1)
            if name in ("os.path.join", "path.join", "join") and node.args:
                return self._joined(node.args, depth)
        return None

    def _resolve_name(self, name: str, depth: int) -> list[str] | None:
        if name in self.parameters:
            if name in self.assigned or len(self.parameters[name]) > 1:
                return None  # the same name in several scopes, which this doesn't track
            function, position = self.parameters[name][0]
            found: list[str] = []
            for call in self.calls.get(function, []):
                paths = self.resolve(call.args[position], depth + 1) if position < len(call.args) else None
                if paths is None:
                    return None
                found += paths
            return found or None
        values = self.assigned.get(name, [])
        return self.resolve(values[0], depth + 1) if len(values) == 1 else None

    def _joined(self, parts: list[ast.AST], depth: int) -> list[str] | None:
        joined = [""]
        for part in parts:
            paths = self.resolve(part, depth + 1)
            if paths is None:
                return None
            joined = [os.path.join(left, right) for left in joined for right in paths]
        return joined


def _is_a_write_mode(mode: ast.AST | None, unknown_counts: bool) -> bool:
    """A file name isn't a mode, which matters because `Image.open('data.png')` has an `a` in it."""
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return bool(MODE.fullmatch(mode.value)) and bool(WRITE_MODE & set(mode.value))
    return unknown_counts


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _path_object(node: ast.AST, paths: _PythonPaths) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    return isinstance(node, ast.Call) and paths.name_of(node.func).rsplit(".", 1)[-1] in ("Path", "PurePath")


def _changed_by(call: ast.Call, paths: _PythonPaths) -> list[ast.AST | None]:
    """The expressions naming what this call changes. A `None` means it writes something this can't name."""
    name = paths.name_of(call.func)
    method = call.func.attr if isinstance(call.func, ast.Attribute) else ""
    if name in FILE_FUNCTIONS:
        return [call.args[position] if position < len(call.args) else None for position in FILE_FUNCTIONS[name]]
    if name in ("open", "zipfile.ZipFile") or (method == "open" and name.split(".")[0] in MODULE_OPENERS):
        mode = call.args[1] if len(call.args) > 1 else _keyword(call, "mode")
        return [call.args[0] if call.args else None] if _is_a_write_mode(mode, name == "open") else []
    if method == "open":  # Path.open, where the mode comes first
        return [call.func.value] if _is_a_write_mode(call.args[0] if call.args else _keyword(call, "mode"), False) else []
    if method in PATH_ONLY_METHODS:
        return [call.func.value]
    if method == "rename" and call.args and (_path_object(call.func.value, paths) or isinstance(call.args[0], ast.Constant) or _path_object(call.args[0], paths)):
        return [call.func.value, call.args[0]]
    if method == "replace" and _path_object(call.func.value, paths):
        return [call.func.value, *call.args[:1]]
    return []


def _runs_something_that_writes(call: ast.Call, paths: _PythonPaths) -> bool:
    """Only a literal command can be judged. A variable one is usually a check, and treating it as an edit would hold every test run."""
    if paths.name_of(call.func) not in RUNS_A_COMMAND or not call.args:
        return False
    command = call.args[0]
    if isinstance(command, (ast.List, ast.Tuple)) and command.elts and isinstance(command.elts[0], ast.Constant):
        program = str(command.elts[0].value)
    elif isinstance(command, ast.Constant) and isinstance(command.value, str) and command.value.split():
        program = command.value.split()[0]
    else:
        return False
    return os.path.basename(program) in COMMANDS_THAT_CHANGE_FILES


def python_writes(code: str | None) -> list[str]:
    """Files this Python changes, with "" where it can't say which. Read from its syntax, so a string that mentions `open` isn't a write.

    It can't follow `exec` of a variable, `__import__`, a renamed `open`, or a library's own writer. docs/failure-modes.md says so.
    """
    if not code:
        return []
    if code.lstrip().startswith("$"):  # `python3 -c "$CODE"`, which can't be read from here
        return [""]
    try:
        if len(code) > MAX_PYTHON_CHARS:
            raise ValueError
        tree = _parsed(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return [""] if LOOKS_LIKE_A_WRITE.search(code[:MAX_PYTHON_CHARS]) else []
    paths = _PythonPaths(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for changed in _changed_by(node, paths):
                found += paths.resolve(changed) or [""]
            if _runs_something_that_writes(node, paths):
                found.append("")
            if paths.name_of(node.func) in ("exec", "eval") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found += python_writes(node.args[0].value)
    return found


def _parsed(code: str) -> ast.AST:
    try:
        return ast.parse(code)
    except SyntaxError:
        return ast.parse(code.replace('\\"', '"').replace("\\$", "$"))  # double-quoted `python3 -c "open(\"a\")"`
