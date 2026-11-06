"""What a shell command does: what it really runs, whether it rewrites files, whether it checks anything, and whether its output shows a pass.

Best-effort, and not a security boundary. A command nothing here recognizes counts as neither a check nor an edit.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
import shlex

# Words the shell reads before a command, so `if x; then rm -rf /; fi` still runs rm.
SHELL_KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "{", "!"}
WRAPPERS = {"sudo", "time", "timeout", "gtimeout", "env", "nice", "command", "exec", "nohup"}
WRAPPER_VALUE = re.compile(r"\d+(\.\d+)?[smhd]?")  # `timeout 60`, `nice -n 10`
# Options whose next word is their value, so `sudo -u root rm` runs rm, not root.
WRAPPER_VALUE_OPTIONS = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "-D", "-R"}, "env": {"-u", "-C", "-S"},
                         "timeout": {"-k", "-s"}, "gtimeout": {"-k", "-s"}, "nice": {"-n"}, "time": {"-f", "-o"}, "exec": {"-a"}}
# `python -m black .`, `uv run black .`, `uvx black .` and `nbqa black n.ipynb` all run black, so they are judged by what they run.
RUNNERS = {"uv", "poetry", "pipenv", "hatch", "pdm", "pipx", "conda", "mamba", "micromamba"}
RUNNER_VALUE_FLAGS = {"--name", "--prefix", "--with", "--from", "--python", "--package", "--extra", "--group",
                      "--directory", "--project", "--env", "--env-file", "--spec", "--config"}
# Short flags differ by runner: `-n` takes a value for conda and means no-cache for uv.
RUNNER_SHORT_VALUE_FLAGS = {"conda": {"-n", "-p"}, "mamba": {"-n", "-p"}, "micromamba": {"-n", "-p"}, "uv": {"-p", "-w"},
                            "uvx": {"-p", "-w"}, "poetry": {"-C", "-P"}, "hatch": {"-e"}, "pdm": {"-p"}}
PYTHON = re.compile(r"python[\d.]*")
PYTHON_MODULE_FLAG = re.compile(r"-[bBdEiIOPqsSuvx]*m")  # `python -m` and `python -Bm`
PYTHON_INFO_ARGS = (["--version"], ["-V"], ["-h"], ["--help"])
PYTHON_VALUE_FLAGS = {"-X", "-W"}

CHECK_TOOLS = {"pytest", "py.test", "tox", "nox", "mypy", "pyright", "ty", "ruff", "flake8", "pylint", "bandit", "pip-audit",
               "vulture", "deptry", "lint-imports", "papermill", "sphinx-build", "cosmic-ray", "stubtest", "eslint", "tsc", "jest", "vitest",
               "mocha", "ava", "playwright", "cypress", "ctest", "cmake", "ninja", "bazel", "make", "mvn", "gradle", "gradlew",
               "rspec", "phpunit", "sqlite3", "psql", "shellcheck", "bats", "golangci-lint", "clang-tidy", "hyperfine"}
PACKAGE_RUN_COMMANDS = {"test", "t", "run", "exec", "lint", "build", "typecheck", "check"}
CARGO_CHECKS = {"test", "check", "clippy", "build", "run", "nextest"}
GO_CHECKS = {"test", "vet", "build", "run"}
# Checks only under one subcommand: `coverage run` runs the code, `pre-commit install` doesn't check anything.
SUBCOMMAND_CHECKS = {"coverage": {"run"}, "pre-commit": {"run"}, "mkdocs": {"build"}, "hatch": {"test"},
                     "pants": {"test", "check", "lint"}, "tach": {"check", "test"}, "mutmut": {"run"}}
NOT_CHECK_PROGRAMS = {"pip", "venv", "virtualenv", "ensurepip", "pydoc", "echo", "ls", "cat", "which", "printenv"}
RUFF_NOT_CHECKS = {"rule", "config", "linter", "version", "clean", "server", "analyze"}
# These ask a tool about itself or list a suite, so they aren't checks and aren't meant to write.
INFO_FLAGS = {"--version", "--help", "--collect-only", "--co", "--markers", "--fixtures", "--fixtures-per-test"}

# Commands that rewrite project files. The value is the flag that makes them write, or None if they always do.
FORMATTERS = {"black": None, "isort": None, "pyupgrade": None, "nbstripout": None, "pip-compile": None, "gofmt": "-w", "rustfmt": None,
              "prettier": "--write", "eslint": "--fix", "ruff": "--fix", "autopep8": "--in-place", "yapf": "--in-place",
              "autoflake": "--in-place", "docformatter": "--in-place"}
FORMATTER_DRY_RUN = {"--check", "--check-only", "--diff", "--dry-run", "--is-stripped", "--verify", "--nbqa-diff"}
RUFF_WRITES = {"--fix", "--fix-only", "--add-noqa"}
IN_PLACE = re.compile(r"-[a-zA-Z]*i[a-zA-Z]*|--in-place")
INSTALLERS = {"npm": {"install", "i", "add"}, "pnpm": {"install", "i", "add"}, "yarn": {"add"}, "bun": {"add", "install"},
              "uv": {"add", "remove", "lock", "sync"}, "poetry": {"add", "remove", "lock", "update"},
              "pdm": {"add", "remove", "lock", "update"}, "cargo": {"add"}, "go": {"get"},
              "pipenv": {"install", "uninstall", "lock", "update"}}
LOCK_CHECKS = {"--check", "--dry-run"}

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Python run straight from the command, and the code it runs: `python3 - <<E`, `python3 -I - args <<E`, `python3 -c "..."`.
_PYTHON = r"\bpython[\d.]*(?:\s+-[A-Za-z]*[A-BD-Za-bd-z])*"
PYTHON_HEREDOC = re.compile(_PYTHON + r"""\s*(?:-(?:\s[^\n;&|<]*)?)?<<-?\s*['"]?(\w+)['"]?[^\n]*\n(.*?)\n\s*\1\b""", re.S)
PYTHON_DASH_C = re.compile(_PYTHON + r"""\s+-[A-Za-z]*c\s+(?:"((?:[^"\\]|\\.)*)"|'([^']*)')""", re.S)
_WRITE_MODE = r"""(?:mode\s*=\s*)?['"](?:[wax]|r\+)[bt+]*['"]"""
PYTHON_WRITE = re.compile(rf"""\bopen\(\s*(?:['"](?P<literal>[^'"\n]+)['"]|(?P<name>\w+)|(?:[^()\n]|\([^()\n]*\))*?)\s*,\s*{_WRITE_MODE}"""
                          rf"""|(?:(?:\w+\.)?Path\(\s*['"](?P<literal2>[^'"\n]+)['"]\s*\)|(?P<name2>\w+)|\S+)\s*\.(?:write_(?:text|bytes)\(|open\(\s*{_WRITE_MODE})""")
PYTHON_NAMED_PATH = re.compile(r"""^\s*(\w+)\s*=\s*(?:\w*Path\(\s*)?['"]([^'"\n]+)['"]""", re.M)
LEADING_CD = re.compile(r"""\s*cd\s+(\S+)\s*(?:&&|;)""")
# A pipe hides the exit status, so `pytest | tail` looks successful with failures in its output.
FAILED_SUMMARY = re.compile(r"\b[1-9]\d* (failed|errors?)\b[^=\n]{0,80} in \d"  # pytest
                            r"|^FAILED \S+::\S|^FAILED \(|^ERROR \S+\.py(::[^\n]*)?( - |$)"  # pytest's short summary, and unittest
                            r"|^ERROR: (usage|file or directory not found|not found)|ImportError while loading conftest"  # pytest couldn't start
                            r"|\bFound [1-9]\d* (errors?|diagnostics?)\b(?! \(\d+ fixed, 0 remaining\))"  # mypy, ruff, ty
                            r"|^[1-9]\d* errors?, \d+ warnings?"  # pyright
                            r"|^\S+\.py:\d+:\d+: [A-Z]+\d+\b"  # findings from flake8, pylint and ruff
                            r"|\bFAIL code \d|\bevaluation failed\b"  # tox
                            r"|^Traceback \(most recent call last\):\n(?:[ \t][^\n]*\n)+[\w.]+(?:Error|Exception|Interrupt|Exit)\b[^\n]*\s*\Z",  # a script that died
                            re.M)


def unquote(word: str) -> str:
    return word[1:-1] if len(word) >= 2 and word[0] == word[-1] and word[0] in "'\"" else word


def head(words: list[str]) -> tuple[str, list[str]]:
    """The program a simple command runs, past environment assignments and wrappers, and its arguments."""
    index = 0
    while index < len(words):
        word = os.path.basename(unquote(words[index]))
        if re.match(r"^\w+=", words[index]) or word in SHELL_KEYWORDS:
            index += 1
        elif word == "command" and words[index + 1:index + 2] in (["-v"], ["-V"]):
            return word, [unquote(rest) for rest in words[index + 1:]]  # only asks whether a program exists
        elif word in WRAPPERS:
            index += 1
            while index < len(words) and (words[index].startswith("-") or WRAPPER_VALUE.fullmatch(words[index])):
                index += 2 if words[index] in WRAPPER_VALUE_OPTIONS.get(word, ()) else 1
        else:
            break
    if index >= len(words):
        return "", []
    return os.path.basename(unquote(words[index])), [unquote(word) for word in words[index + 1:]]


def _past_options(words: list[str], runner: str = "") -> list[str]:
    short = RUNNER_SHORT_VALUE_FLAGS.get(runner, ())
    rest = list(words)
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in RUNNER_VALUE_FLAGS or rest[0] in short else rest[1:]
    return rest


def _handed_to(name: str, args: list[str]) -> list[str] | None:
    """The command line a runner hands on, or None if this isn't a runner."""
    if PYTHON.fullmatch(name):
        rest = list(args)
        while rest and rest[0].startswith("-") and not PYTHON_MODULE_FLAG.fullmatch(rest[0]):
            rest = rest[2:] if rest[0] in PYTHON_VALUE_FLAGS else rest[1:]
        return rest[1:] if rest and PYTHON_MODULE_FLAG.fullmatch(rest[0]) else None
    if name in ("uvx", "nbqa"):
        return _past_options(args, name)
    if name in RUNNERS:
        rest = _past_options(args, name)
        if rest[:2] == ["tool", "run"]:
            return _past_options(rest[2:], name)
        return _past_options(rest[1:], name) if rest[:1] == ["run"] else None
    return None


def run_by(words: list[str]) -> tuple[str, list[str]]:
    """Like head, and also past runners, however many: `uv run python -m black .` gives black."""
    name, args = head(words)
    while True:
        handed = _handed_to(name, args)
        if not handed:
            return name, args
        name, args = re.split(r"[@=<>!~\[]", os.path.basename(handed[0]))[0], handed[1:]  # `uvx black@latest`, `uvx black==26.1`


def is_info_only(args: list[str]) -> bool:
    # `-V` only alone and `-h` only last, since `ctest -V` means verbose and `psql -h db` names a host.
    return bool(INFO_FLAGS & set(args)) or args[-1:] == ["-h"] or args == ["-V"]


def is_dry_run(name: str, args: list[str]) -> bool:
    return name in FORMATTERS and bool(FORMATTER_DRY_RUN & set(args) or (name == "isort" and "-c" in args))


def _ruff_formats(name: str, args: list[str]) -> bool:
    return name == "ruff" and _past_options(args)[:1] == ["format"]


def rewrites_files(name: str, args: list[str]) -> bool:
    if name not in FORMATTERS or is_dry_run(name, args) or is_info_only(args):
        return False
    flag = FORMATTERS[name]
    if name == "ruff":
        return (_ruff_formats(name, args) and "-" not in args) or bool(RUFF_WRITES & set(args))  # `-` is stdin to stdout
    if flag == "--in-place":
        return any(IN_PLACE.fullmatch(arg) for arg in args)
    return flag is None or flag in args


def _changes_manifest(name: str, args: list[str]) -> bool:
    rest = _past_options(args, name)
    if name not in INSTALLERS or not rest or rest[0] not in INSTALLERS[name] or LOCK_CHECKS & set(args):
        return False
    if rest[0] == "lock" and "--locked" in args:  # asserts the lockfile is current
        return False
    return name != "npm" or sum(not arg.startswith("-") for arg in args) > 1


def writes_project_files(name: str, args: list[str]) -> bool:
    """Does this command write project files without naming them? Give it what run_by returns."""
    if is_info_only(args):
        return False
    if rewrites_files(name, args) or _changes_manifest(name, args):
        return True
    if name == "pre-commit":  # its hooks commonly reformat
        return args[:1] == ["run"]
    if name == "uv":
        return args[:2] == ["pip", "compile"] and any(arg == "-o" or arg.startswith("--output-file") for arg in args)
    if name == "piptools":
        return args[:1] == ["compile"]
    return name == "cargo" and args[:1] == ["fmt"] and "--check" not in args


def nbconvert_target(args: list[str]) -> str | None:
    """Where `jupyter nbconvert` writes: a folder, "" for beside the notebook, or None for nowhere."""
    if args[:1] != ["nbconvert"] or is_info_only(args) or "--stdout" in args:
        return None
    if "--inplace" in args:
        return ""
    for index, arg in enumerate(args):
        if arg.startswith("--output-dir="):
            return os.path.expanduser(unquote(arg.split("=", 1)[1]))
        if arg == "--output-dir" and index + 1 < len(args):
            return os.path.expanduser(args[index + 1])
    return ""


def is_check(words: list[str]) -> bool:
    """Does this simple command run tests, a build, a checker, or the code itself?"""
    name, args = head(words)
    first = args[0] if args else ""
    program, program_args = run_by(words)
    # Only for known tools, because `python cli.py --help` really does run the code.
    if (program in CHECK_TOOLS or program in FORMATTERS or program in SUBCOMMAND_CHECKS) and is_info_only(program_args):
        return False
    if PYTHON.fullmatch(program) and program_args in PYTHON_INFO_ARGS:
        return False
    if program == "ruff" and _past_options(program_args)[:1] and _past_options(program_args)[0] in RUFF_NOT_CHECKS:
        return False
    # A formatting pass says nothing about behavior, while `ruff check --fix` and `eslint --fix` also lint.
    if _ruff_formats(program, program_args):
        return False
    if is_dry_run(program, program_args) or rewrites_files(program, program_args):
        return program in CHECK_TOOLS
    if program in SUBCOMMAND_CHECKS:
        return program_args[:1] != [] and program_args[0] in SUBCOMMAND_CHECKS[program]
    if program == "jupyter":
        return "--execute" in program_args or program_args[:1] == ["execute"]
    if program != name:
        return program not in NOT_CHECK_PROGRAMS
    if name in CHECK_TOOLS or name in ("npx", "bunx", "pnpx") and first:
        return True
    if name in ("uv", "poetry", "pipenv", "hatch", "pdm"):
        return first == "run" and len(args) > 1
    if name in ("npm", "yarn", "pnpm", "bun"):
        return first in PACKAGE_RUN_COMMANDS
    if name == "cargo":
        return first in CARGO_CHECKS
    if name == "go":
        return first in GO_CHECKS
    if name == "node":
        return bool(first) and first not in ("--version", "-v")
    if PYTHON.fullmatch(name):
        return bool(first) and first not in ("--version", "-V", "-h", "--help") and args[:2] != ["-m", "pip"]
    if name in ("bash", "sh", "zsh"):
        return bool(first) and first != "-c"
    return unquote(words[0]).startswith("./")


def output_text(response: object) -> str:
    """A tool's output as plain text. Color codes and escaped newlines would defeat the word boundaries in these patterns."""
    return ANSI.sub("", "\n".join(_strings(response)))


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        value = list(value.values())
    return [text for item in value for text in _strings(item)] if isinstance(value, (list, tuple)) else []


def shows_no_pass(output: str) -> bool:
    from occam_tools.zero_tests import ran_no_tests  # on sys.path through scan_notes, and imported late so a problem there fails open

    return bool(ran_no_tests(output) or FAILED_SUMMARY.search(output))


def logical_lines(text: str) -> list[str]:
    """Split where a shell ends a command, which isn't every newline: quotes span lines and a backslash joins the next one.

    Splitting at each newline made the lexer give up on a line with a multi-line quote, hiding `pytest` or `rm` in
    `pytest -q && git commit -m "a<newline>b"`. Comments go, because an apostrophe in one isn't a quote, and `# clean; rm -rf /`
    isn't a command. A quote that never closes isn't valid shell, so from that command on this falls back to every newline.
    """
    lines: list[str] = []
    current: list[str] = []
    quote = ""
    start = index = 0
    while index < len(text):
        char = text[index]
        if quote:
            step = 2 if char == "\\" and quote == '"' else 1
            current.append(text[index:index + step])
            quote = "" if char == quote else quote
            index += step
        elif char == "\\":
            current.append(" " if text[index + 1:index + 2] == "\n" else text[index:index + 2])
            index += 2
        elif char == "#" and (not current or current[-1][-1:] in tuple(" \t;&|(")):
            newline = text.find("\n", index)
            index = newline if newline >= 0 else len(text)
        elif char == "\n":
            lines.append("".join(current))
            current = []
            index += 1
            start = index
        else:
            quote = char if char in "'\"" else ""
            current.append(char)
            index += 1
    return lines + text[start:].split("\n") if quote else lines + ["".join(current)]


def shell_tokens(line: str) -> list[str]:
    """Words and operators. If the quotes don't balance, read them as ordinary characters, so a stray one can't hide the line."""
    for quotes in ("'\"", ""):
        lexer = shlex.shlex(line, posix=False, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        lexer.quotes = quotes
        try:
            return list(lexer)
        except ValueError:
            continue
    return []


def inline_python_writes(command: str) -> list[str]:
    """Files that Python run straight from the command writes, with "" where the code doesn't say which.

    Only the code that runs here: a script written out with `cat > gen.py <<E` writes nothing until something runs it.
    """
    code = [match.group(2) for match in PYTHON_HEREDOC.finditer(command)]
    code += [match.group(1) or match.group(2) or "" for match in PYTHON_DASH_C.finditer(command)]
    folder = LEADING_CD.match(command)
    prefix = unquote(folder.group(1)) if folder else ""
    targets = []
    for body in code:
        named = dict(PYTHON_NAMED_PATH.findall(body))
        for match in PYTHON_WRITE.finditer(body):
            path = match.group("literal") or match.group("literal2") or named.get(match.group("name") or match.group("name2") or "")
            targets.append("" if not path else path if path.startswith("$") else os.path.join(prefix, path))
    return targets


def runs_inline_python(words: list[str]) -> bool:
    """Is this simple command Python running code from the command line, rather than a script or module?"""
    name, args = head(words)
    return bool(PYTHON.fullmatch(name)) and (all(arg.startswith("-") for arg in args) or any(re.fullmatch(r"-[A-Za-z]*c", arg) for arg in args))


def golden_command(args: list[str]) -> list[str]:
    """What `occam golden record NAME ...` will run, read the way the tool reads it, with or without `--`."""
    if "record" not in args or args.index("record") + 1 >= len(args):
        return []
    rest = args[args.index("record") + 2:]
    index = 0
    while index < len(rest) and rest[index] in ("--normalize", "--timeout"):
        index += 2
    return rest[index + 1:] if rest[index:index + 1] == ["--"] else rest[index:]
