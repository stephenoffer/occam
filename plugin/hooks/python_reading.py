"""What inline Python does, read with `ast` rather than patterns: the files it writes, the credential files it prints, and the downloads it
runs as code. Each reads the code a shell step hands to Python, as `python3 - <<'EOF'` or `python3 -c "..."`, and code it can't parse says
nothing. Values are followed through plain assignments, loops and a few calls that hand back what they're given, and no further.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import ast
import os
import re
from collections import defaultdict
from typing import Callable

MAX_PYTHON_CHARS = 100_000  # Python 3.9's parser segfaults on deep expressions from about 210,000 characters, and no `except` catches that.
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


def _parsed_or_none(code: str | None) -> ast.AST | None:
    if not code or len(code) > MAX_PYTHON_CHARS or code.lstrip().startswith("$"):
        return None
    try:
        return _parsed(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


FETCHES = {"urlopen", "urlretrieve", "get", "post", "request", "stream"}
FETCH_MODULES = ("urllib", "requests", "httpx", "urllib3", "aiohttp", "http")
RUNS_CODE = {"exec", "eval", "compile", "builtins.exec", "builtins.eval", "os.system", "subprocess.run", "subprocess.call", "subprocess.check_call",
             "subprocess.check_output", "subprocess.Popen", "runpy.run_path"}
EVALUATES = {"exec", "eval", "compile", "builtins.exec", "builtins.eval", "runpy.run_path"}
# Programs that run code they're given: as a script file, the first word that isn't an option, or inline after one of these.
INTERPRETER = re.compile(r"(?:.*/)?(?:python[\d.]*|pypy3?|bash|sh|zsh|dash|ksh|fish|node|deno|bun|perl|ruby|php|pwsh|powershell|osascript)")
INLINE_CODE = {"-c", "-e", "--eval", "-Command", "-command", "-EncodedCommand"}


# What an expression holds when it's one of its parts: an element, a value in an f-string, either side of an operator or a condition, an item.
_HELD_PARTS = (((ast.Subscript, ast.Starred), lambda node: (node.value,)),
               (ast.JoinedStr, lambda node: [part.value for part in node.values if isinstance(part, ast.FormattedValue)]),
               (ast.BinOp, lambda node: (node.left, node.right)), (ast.BoolOp, lambda node: node.values), (ast.IfExp, lambda node: (node.body, node.orelse)),
               ((ast.Tuple, ast.List, ast.Set), lambda node: node.elts))
_CARRYING_ATTRIBUTES = ("password", "netloc", "userinfo", "text", "content")  # parts of a value that hold it, as a URL's password or a response's text
_PASSING_METHODS = ("get", "items", "values", "copy", "pop", "read", "decode", "strip", "splitlines", "json")
_KEY_LISTS = ("list", "sorted", "tuple")  # of a mapping, its keys
_PASSING_FUNCTIONS = ("str", "repr", "dict", "list", "sorted", "json.dumps", "json.load", "json.loads", "pprint.pformat", "compile", "bytes", "tuple")


class _Flow:
    """Names in a short script that hold something of interest, followed through plain assignments and loops in a few passes."""

    def __init__(self, tree: ast.AST, source: Callable[[ast.AST], str | None], keys_carry: bool = True) -> None:
        """`keys_carry` says whether a mapping's keys hold what it holds: a downloaded mapping's do, and a credential file's are only names."""
        self.paths = _PythonPaths(tree)
        self.source = source
        self.keys_carry = keys_carry
        self.held: dict[str, str] = {}
        self.derived: dict[str, str] = {}
        self.mappings: set[str] = set()  # names bound to a mapping as it was read, whose iteration gives keys
        assignments = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign, ast.For, ast.withitem))]
        for _ in range(3):  # a chain of assignments a few deep, written in any order
            for node in assignments:
                self._bind(node)

    def _bind(self, node: ast.AST) -> None:
        if isinstance(node, ast.For):
            self._bind_loop(node)
        else:
            self._bind_assignment(node)

    def _bind_loop(self, node: ast.For) -> None:
        """`for key, value in held.items()` and `for value in held.values()` hold what the mapping holds."""
        loop = node.iter
        method = loop.func.attr if isinstance(loop, ast.Call) and isinstance(loop.func, ast.Attribute) else ""
        held = self.carries(loop.func.value) if method in ("items", "values") else None
        target = node.target
        if held and method == "items" and isinstance(target, ast.Tuple) and len(target.elts) == 2 and isinstance(target.elts[1], ast.Name):
            self.held[target.elts[1].id] = held
        elif held and method == "values" and isinstance(target, ast.Name):
            self.held[target.id] = held

    def _bind_assignment(self, node: ast.AST) -> None:
        value = node.context_expr if isinstance(node, ast.withitem) else node.value
        targets = [node.optional_vars] if isinstance(node, ast.withitem) else node.targets if isinstance(node, ast.Assign) else [node.target]
        if value is None:
            return
        held, derived = self.carries(value), self.derived_from(value)
        self.mappings.update(target.id for target in targets if isinstance(target, ast.Name) and self._a_mapping(value))
        for target in targets:
            if isinstance(target, ast.Name) and held:
                self.held[target.id] = held
            elif isinstance(target, ast.Name) and derived:
                self.derived[target.id] = derived

    def carries(self, node: ast.AST | None, depth: int = 0) -> str | None:
        """What this expression holds as it is, not something worked out from it."""
        if node is None or depth > 20:
            return None
        found = self.source(node)
        if found:
            return found
        if isinstance(node, ast.Name):
            return self.held.get(node.id)
        if isinstance(node, ast.Attribute):
            return self.derived_from(node.value, depth + 1) if node.attr in _CARRYING_ATTRIBUTES else None
        if isinstance(node, ast.Call):
            return self._call_carries(node, depth)
        parts = next((parts for types, parts in _HELD_PARTS if isinstance(node, types)), None)
        return self.first_carried(parts(node), depth) if parts else None

    def _call_carries(self, node: ast.Call, depth: int) -> str | None:
        """A method or function that hands back what it's given, as `.get()`, `str()` and `json.loads()` do."""
        if isinstance(node.func, ast.Attribute) and node.func.attr in _PASSING_METHODS:
            return self.carries(node.func.value, depth + 1)
        name = self.paths.name_of(node.func)
        if name in _KEY_LISTS and not self.keys_carry and node.args and self._a_mapping(node.args[0]):
            return None  # `sorted(dotenv_values('.env'))` lists the names, which say what's set without the values
        if name in _PASSING_FUNCTIONS:
            return self.first_carried(node.args, depth)
        return None

    def _a_mapping(self, node: ast.AST) -> bool:
        """A mapping as it was read: what dotenv_values or a loader returns, a response's `.json()`, or a name bound to one."""
        if isinstance(node, ast.Name):
            return node.id in self.mappings
        if not isinstance(node, ast.Call):
            return False
        name = self.paths.name_of(node.func)
        return name.rsplit(".", 1)[-1] in ("dotenv_values", "load_dotenv_values") or name in _LOADERS or name == "json.loads" or (
            isinstance(node.func, ast.Attribute) and node.func.attr == "json")

    def first_carried(self, nodes, depth: int) -> str | None:
        return next((found for node in nodes for found in [self.carries(node, depth + 1)] if found), None)

    def derived_from(self, node: ast.AST | None, depth: int = 0) -> str | None:
        """An object made from something held, as `urlsplit(url)` is, whose parts may or may not carry it."""
        if node is None or depth > 20:
            return None
        if isinstance(node, ast.Name) and node.id in self.derived:
            return self.derived[node.id]
        held = self.carries(node, depth + 1)
        if held:
            return held
        if isinstance(node, ast.Call):
            return next((found for arg in node.args for found in [self.carries(arg, depth + 1)] if found), None)
        return None


def _secret_file_source(paths: _PythonPaths, is_secret_file: Callable[[str], bool]) -> Callable[[ast.AST], str | None]:
    def source(node: ast.AST) -> str | None:
        if not isinstance(node, ast.Call):
            return None
        files = _files_a_call_reads(paths, node, source)
        return next((path for path in files or [] if path and is_secret_file(path.replace("\\", "/"))), None)
    return source


_LOADERS = ("json.load", "yaml.safe_load", "yaml.load", "tomllib.load", "toml.load")  # each reads a file another call opened


def _files_a_call_reads(paths: _PythonPaths, node: ast.Call, source: Callable[[ast.AST], str | None]) -> list[str] | None:
    """The files a call reads: what dotenv_values names, `.env` by default; what open() names; for a loader, the file `source` finds its
    argument opened; and for `.read_text()` and the like, the path the call it's on names."""
    name = paths.name_of(node.func)
    if name.rsplit(".", 1)[-1] in ("dotenv_values", "load_dotenv_values"):
        return paths.resolve(node.args[0]) if node.args else [".env"]
    if name in ("open", "io.open"):
        return paths.resolve(node.args[0] if node.args else None)
    if name in _LOADERS:
        return [source(node.args[0]) or ""] if node.args else None
    if isinstance(node.func, ast.Attribute) and node.func.attr in ("read_text", "read_bytes", "read"):
        return paths.resolve(node.func.value.args[0]) if isinstance(node.func.value, ast.Call) and node.func.value.args else None
    return None


PRINTERS = {"print", "pprint", "pprint.pprint", "sys.stdout.write", "sys.stderr.write", "builtins.print"}


def python_prints_a_secret_file(code: str | None, is_secret_file: Callable[[str], bool]) -> str | None:
    """The credential file this Python prints values from, as `print(dotenv_values('.env')[k])` does. A part worked out from a value,
    such as a URL's host, isn't the value."""
    tree = _parsed_or_none(code)
    if tree is None:
        return None
    paths = _PythonPaths(tree)
    flow = _Flow(tree, _secret_file_source(paths, is_secret_file), keys_carry=False)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and paths.name_of(node.func) in PRINTERS:
            found = next((found for arg in [*node.args, *(keyword.value for keyword in node.keywords if keyword.arg != "file")]
                          for found in [flow.carries(arg)] if found), None)
            if found:
                return found
    return None


def _fetch_source(paths: _PythonPaths) -> Callable[[ast.AST], str | None]:
    def source(node: ast.AST) -> str | None:
        if not isinstance(node, ast.Call):
            return None
        name = paths.name_of(node.func)
        last = name.rsplit(".", 1)[-1]
        return "a download" if last in FETCHES and (name.startswith(FETCH_MODULES) or last in ("urlopen", "urlretrieve")) else None
    return source


def python_runs_a_download(code: str | None) -> bool:
    """Does this Python run something it fetched as code, as `exec(urlopen(url).read())` does? Fetched data passed as one argument among
    others, as `subprocess.run(['git', 'fetch', 'origin', branch])` passes a branch name, isn't run."""
    tree = _parsed_or_none(code)
    if tree is None:
        return False
    paths = _PythonPaths(tree)
    flow = _Flow(tree, _fetch_source(paths))
    return any(isinstance(node, ast.Call) and paths.name_of(node.func) in RUNS_CODE and _runs_as_code(node, paths.name_of(node.func), flow) for node in ast.walk(tree))


def _runs_as_code(call: ast.Call, name: str, flow: _Flow) -> bool:
    first = call.args[0] if call.args else next((keyword.value for keyword in call.keywords if keyword.arg in ("args", "source", "command", "path_name")), None)
    if first is None:
        return False
    if name in EVALUATES:
        return bool(flow.carries(first))
    if not isinstance(first, (ast.List, ast.Tuple)):
        return _begins_with_a_download(first, flow)  # the program, or with a shell the script, which a fetched value starting it decides
    return _program_runs_a_download(first.elts, flow)


def _program_runs_a_download(words: list[ast.AST], flow: _Flow) -> bool:
    """A program and its arguments as a list: the download runs when it's the program, or what an interpreter there runs."""
    if not words:
        return False
    if flow.carries(words[0]):
        return True
    program = words[0].value if isinstance(words[0], ast.Constant) else None
    return isinstance(program, str) and bool(INTERPRETER.fullmatch(program)) and _interpreter_runs_a_download(words[1:], flow)


def _interpreter_runs_a_download(rest: list[ast.AST], flow: _Flow) -> bool:
    """The code an interpreter's arguments give it, inline after `-c` or as the first word that isn't an option, is a download."""
    for index, item in enumerate(rest):
        word = item.value if isinstance(item, ast.Constant) else None
        if word in INLINE_CODE:
            return index + 1 < len(rest) and bool(flow.carries(rest[index + 1]))
        if not (isinstance(word, str) and word.startswith("-")):
            return bool(flow.carries(item))  # the script file it runs
    return False


def _begins_with_a_download(node: ast.AST, flow: _Flow) -> bool:
    if isinstance(node, ast.BinOp):
        return _begins_with_a_download(node.left, flow)
    if isinstance(node, ast.JoinedStr):
        return bool(node.values) and isinstance(node.values[0], ast.FormattedValue) and bool(flow.carries(node.values[0].value))
    return bool(flow.carries(node))


def _parsed(code: str) -> ast.AST:
    try:
        return ast.parse(code)
    except SyntaxError:
        return ast.parse(code.replace('\\"', '"').replace("\\$", "$"))  # double-quoted `python3 -c "open(\"a\")"`
