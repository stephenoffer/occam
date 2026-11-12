"""What a shell command does to the project: what it writes, step by step, whether a step ran here at all, and what it could lose.

Read in order through `shell_reading`, so a `cd` only affects the steps after it. Best-effort, and not a security boundary:
docs/failure-modes.md lists what gets past it.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
from pathlib import Path
from typing import Any, NamedTuple

import occam_evidence as evidence
import scan_notes
from destructive import MAX_MAKEFILE_BYTES, is_generated, make_deletes_through_unset, names_production, production_target, restore_reason, set_in_environment
from occam_commands import (INSTALLERS, RUNS_A_FILE, golden_command, head, is_check, nbconvert_target, option_value, output_text, rewrites_in_place, run_by, settings_of,
                             unquote, writes_project_files)
from printed_secrets import SECRET_FILE, secret_printed
from python_reading import python_prints_a_secret_file, python_runs_a_download, python_writes
from session_state import Session, record
from shell_reading import expand_variables, git_commands, home_expanded, parse_shell, read_steps, without_heredoc_bodies

TEMP_VARIABLES = {"TMPDIR", "TMP", "TEMP"}
TEMP_FOLDERS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
GIT_CHANGES_FILES = {"merge", "pull", "cherry-pick", "revert", "am", "checkout", "switch", "restore", "reset", "stash", "clean", "rebase"}
GIT_GLOBAL_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
SCRIPT_RUNNERS = {"perl", "ruby", "node", "php"}
SCRIPT_WRITES = re.compile(r"\b(?:unlink|File\.delete|File\.write|unlinkSync|writeFileSync|rmSync|open)\b")
CHECK_FOLDER_OPTIONS = ("--rootdir=",)
GIT = r"^git(?:\s+(?:-[cC]\s+\S+|--(?:git-dir|work-tree|namespace)\s+\S+|--[\w-]+(?:=\S+)?))*\s+"
# Each of these can lose work, and a word in a prompt ("fix the password reset flow") isn't consent.
DESTRUCTIVE_GIT = {
    "reset": re.compile(GIT + r"reset\b[^;&|]*--hard"),
    "checkout": re.compile(GIT + r"checkout\s+(?:[^;&|]*\s)?(?:--\s|\.(?:\s|$))"),
    "restore": re.compile(GIT + r"restore(?=\s)(?:(?![^;&|]*(?:--staged\b|\s-[a-zA-Z]*S))|(?=[^;&|]*(?:--worktree\b|\s-[a-zA-Z]*W)))"),  # unstaging alone loses nothing
    "clean": re.compile(GIT + r"clean\b[^;&|]*\s-[a-zA-Z]*f"),
    "stash": re.compile(GIT + r"stash\b(?!\s+(?:list|show)\b)"),
    # Forcing (`--force`, `-f`, a `+main` refspec) or deleting what the remote has (`--delete`, `-d`, `:old`, `--mirror`, `--prune`).
    "push": re.compile(GIT + r"push\b[^;&|]*(?:--force|--delete\b|--mirror\b|--prune\b|\s-[a-zA-Z]*[fd]|\s[+:][^\s;&|])"),
    "rebase": re.compile(GIT + r"rebase\b"),
    "commit --amend": re.compile(GIT + r"commit\b[^;&|]*--amend\b"),
    "branch": re.compile(GIT + r"branch\s+[^;&|]*-D\b"),
}
# Anything beyond one plain command with plain paths can change what those paths mean.
NOT_PLAIN = re.compile(r"[;&|`$(){}*?\[\]~\"'\\\n]|\s(?:-C|--chdir)\b")


def is_under(path: str, folder: str | None) -> bool:
    if not folder:
        return False
    root = os.path.realpath(folder)
    return path == root or path.startswith(root + os.sep)


def in_project(file_path: str, event: dict) -> bool:
    """True for files in the project. Scratch files and anything outside the project aren't held."""
    cwd = event.get("cwd") or os.getcwd()
    path = os.path.realpath(os.path.join(cwd, file_path))
    if is_under(path, event.get("scratchpad_dir")):
        return False
    return is_under(path, cwd) or is_under(path, os.environ.get("CLAUDE_PROJECT_DIR"))


def inside_project(path: str, event: dict) -> bool | None:
    """Under the project or the working directory, and not one of them, so deleting it can't take the whole thing.

    None for one of them or a folder holding one, wherever that is: a project made in a temp folder is still the whole project.
    """
    roots = [os.path.realpath(root) for root in (event.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")) if root]
    real = os.path.realpath(path)
    holds = real.rstrip(os.sep) + os.sep
    return None if any(root == real or root.startswith(holds) for root in roots) else in_project(path, event)


def project_path(word: str, event: dict) -> bool:
    word = re.sub(r"^\$\{?PWD\}?/?", "", word) or "."
    if not word or word.startswith(("$", "/dev/", "-", "&")) or word.isdigit():
        return False
    return in_project(os.path.expanduser(word), event)


def is_temp_variable(word: str, command: str) -> bool:
    """`$TMPDIR`, `$(mktemp -d)`, or a variable this command set from `mktemp`."""
    if "mktemp" in word:
        return True
    variable = re.match(r"\$\{?(\w+)", word)
    return bool(variable) and (variable.group(1) in TEMP_VARIABLES or bool(re.search(rf"\b{variable.group(1)}=[\"']?(?:\$\(|`)mktemp\b", command)))


def leaves_project(place: str, event: dict, command: str) -> bool:
    """True for a `cd` known to go elsewhere. An unknown variable can lead straight back, so it isn't."""
    if place.startswith("$") or "$(" in place or "`" in place:
        return is_temp_variable(place, command)
    return not in_project(os.path.expanduser(place), event)


_STEPS: dict[tuple, list] = {}  # the hook reads one command's steps several times in a call


def shell_steps(command: str, event: dict) -> list:
    key = (command, event.get("cwd"), event.get("scratchpad_dir"))
    if key not in _STEPS:
        _STEPS.clear()
        _STEPS[key] = read_steps(command, lambda place: leaves_project(place, event, command))
    return _STEPS[key]


def shell_edits(command: str, event: dict) -> list[str]:
    """Paths this command writes in the project, with "" where it writes but the path isn't clear. Best-effort."""
    return [edit for step in shell_steps(command, event) for edit in step_edits(step, event, command)]


def located(step, path: str) -> str:
    return os.path.join(step.folder, path) if step.folder and not os.path.isabs(path) and not path.startswith("$") else path


def step_owns(step, path: str, event: dict) -> bool:
    """Is this path in the project, from where this step runs? After a `cd` to somewhere unnamed, only an absolute path can be."""
    if step.elsewhere and not step.folder and not os.path.isabs(path):
        return False
    return project_path(located(step, path), event)


def _git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in GIT_GLOBAL_VALUE_OPTIONS else 1
    return (args[index], args[index + 1:]) if index < len(args) else ("", [])


def _runs_a_writer(words: list[str]) -> bool:
    """For what `find -exec` or `xargs` hands on to. `sed` reads, unless it's rewriting in place."""
    return words[0] not in evidence.READ_ONLY_PROGRAMS or rewrites_in_place(words[0], words[1:])


class _Writer(NamedTuple):
    """One step, with what deciding its writes needs."""
    step: Any
    event: dict
    command: str

    def ours(self, path: str) -> bool:
        return step_owns(self.step, path, self.event)

    def named(self, paths: list[str]) -> list[str]:
        """Named paths that are the project's. A variable can't be judged, so it reads as unclear unless it's known to be temp."""
        found = []
        for path in map(home_expanded, paths):
            if path.startswith("$") and "PWD" not in path[:6]:
                if not is_temp_variable(path, self.command):
                    found.append("")
            elif self.ours(path):
                found.append(located(self.step, path))
        return found


def _every_path(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    return writer.named(paths)


def _last_path(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    return writer.named(paths[-1:])


def _dd(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    return writer.named([arg[3:] for arg in args if arg.startswith("of=")])


def _git(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    subcommand, rest = _git_subcommand(args)
    if subcommand in ("rm", "mv"):
        return writer.named([arg for arg in rest if not arg.startswith("-")])
    changes = subcommand == "apply" or (subcommand in GIT_CHANGES_FILES and "-b" not in rest and "-B" not in rest and "--dry-run" not in rest and rest[:1] != ["list"])
    return [""] if changes else []


def _patch(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    return [""] if (not paths and not writer.step.elsewhere) or any(writer.ours(path) for path in paths) else []


def _find(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    root = args[0] if args and not args[0].startswith("-") else "."
    start = next((index + 1 for index, arg in enumerate(args[:-1]) if arg in ("-exec", "-execdir", "-ok")), None)
    return [""] if ("-delete" in args or (start is not None and _runs_a_writer(args[start:]))) and writer.ours(root) else []


def _xargs(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    start = next((index for index, arg in enumerate(args) if not arg.startswith("-") and not arg.isdigit()), None)
    return [""] if start is not None and _runs_a_writer(args[start:]) and not writer.step.elsewhere else []


def _download(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    edits: list[str] = []
    for index, arg in enumerate(args):
        if arg in ("-o", "--output", "-O", "--output-document") and index + 1 < len(args):
            edits += writer.named([args[index + 1]])
        elif re.match(r"-o[^-]", arg):
            edits += writer.named([arg[2:]])
    return edits


def _papermill(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    return [located(writer.step, paths[1])] if len(paths) > 1 and writer.ours(paths[1]) else []


def _jupyter(writer: _Writer, args: list[str], paths: list[str]) -> list[str]:
    target = nbconvert_target(args)
    return [target] if target == "" or (target and writer.ours(target)) else []


WRITERS = {**dict.fromkeys(("tee", "truncate", "touch", "rm", "mv", "unlink", "rmdir", "gzip", "bzip2", "xz"), _every_path),
           **dict.fromkeys(("cp", "ln", "install", "rsync"), _last_path),
           "dd": _dd, "git": _git, "patch": _patch, "find": _find, "xargs": _xargs, "curl": _download, "wget": _download}
WRITERS_AFTER_FORMATTERS = {"papermill": _papermill, "jupyter": _jupyter}


def _occam_writes(step, writer: _Writer) -> list[str]:
    """When the step runs occam's own tool: `--out` writes, and `golden` runs whatever follows it, so that gets judged."""
    tool = scan_notes.occam_subcommand(step.words)
    if not tool:
        return []
    if "--out" in tool[1]:
        return [""]
    if tool[0] != "golden":
        return []
    inner = read_steps(" ".join(golden_command(tool[1])), lambda place: leaves_project(place, writer.event, writer.command))
    return [edit for each in inner for edit in step_edits(each._replace(elsewhere=step.elsewhere, folder=step.folder), writer.event, writer.command)]


def _program_writes(name: str, args: list[str], writer: _Writer) -> list[str]:
    paths = [arg for arg in args if not arg.startswith("-")]
    if name in ("sed", "perl", "ruby") and rewrites_in_place(name, args):  # BSD sed's `-i ''` puts an empty word before the script
        files = paths[2 if paths[:1] == [""] else 1:]
        return writer.named(files) if files else [""]
    if name in SCRIPT_RUNNERS and any(arg == "-e" for arg in args) and any(SCRIPT_WRITES.search(arg) for arg in args):
        return [""]
    if name in WRITERS:
        return WRITERS[name](writer, args, paths)
    if writes_project_files(name, args):
        absolute = [path for path in paths if os.path.isabs(path)]
        return [""] if any(writer.ours(path) for path in absolute) or (not absolute and not writer.step.elsewhere) else []
    return WRITERS_AFTER_FORMATTERS[name](writer, args, paths) if name in WRITERS_AFTER_FORMATTERS else []


def step_edits(step, event: dict, command: str = "") -> list[str]:
    """What one step writes in the project."""
    writer = _Writer(step, event, command)
    edits = writer.named(step.targets)
    for path in python_writes(step.code):
        if "$" in path and not is_temp_variable(path, command):  # a shell variable inside the code, which can't be read from here
            edits.append("")
        elif not path or writer.ours(path):
            edits.append(located(step, path) if path else "")
    if not step.words:
        return edits
    name, args = run_by(step.words)
    return edits + _occam_writes(step, writer) + _program_writes(name, args, writer)


def checks_elsewhere(step, event: dict, command: str) -> bool:
    """Did this check run on something other than this code? That's how a new test shows it fails on the old code.

    Naming a path in the project keeps it this code's, wherever it ran from. A run that names only paths outside isn't, and neither is
    one pointed at a temp copy through PYTHONPATH.
    """
    _, args = run_by(step.words)
    named = [arg.split("=", 1)[1] if arg.startswith(CHECK_FOLDER_OPTIONS) else arg for arg in args if arg.startswith(CHECK_FOLDER_OPTIONS) or not arg.startswith("-")]
    absolute = [os.path.expanduser(arg) for arg in named if os.path.isabs(os.path.expanduser(arg))]
    if any(in_project(arg, event) for arg in absolute):
        return False
    if step.elsewhere:
        return True
    # `cc hello.c -o /tmp/h` builds this code, wherever the result goes, and a word only counts as a path here if it is one.
    here = event.get("cwd") or os.getcwd()
    if absolute and not any(os.path.exists(os.path.join(here, arg)) for arg in named if not os.path.isabs(os.path.expanduser(arg))):
        return True
    if absolute:
        return False
    pythonpath = next((word.split("=", 1)[1] for word in step.words if word.startswith("PYTHONPATH=")), "")
    place = unquote(pythonpath)
    return bool(place) and ":" not in place and (is_temp_variable(place, command) or place.startswith(TEMP_FOLDERS))


def relative_path(file_path: str, event: dict) -> str:
    """Relative to the project, so a parent directory's name can't make every file look high consequence."""
    if not file_path:
        return ""
    cwd = event.get("cwd") or os.getcwd()
    path = os.path.realpath(os.path.join(cwd, file_path))
    for root in (os.environ.get("CLAUDE_PROJECT_DIR"), cwd):
        if root and is_under(path, root):
            return os.path.relpath(path, os.path.realpath(root)).replace("\\", "/")
    return file_path.replace("\\", "/")


def project_root(event: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd())


def absolute_path(event: dict, file_path: str) -> Path:
    """A recorded path is relative to the project, and a shell's `cd` can have moved `cwd` away from its root."""
    return project_root(event) / file_path


def deleted_paths(command: str, event: dict) -> list[str]:
    found = []
    for step in shell_steps(command, event):
        name, args = head(step.words)
        if name == "git" and args[:1] == ["rm"] and "--cached" not in args:
            args = args[1:]
        elif name != "rm":
            continue
        found += [relative_path(located(step, arg), event) for arg in args if not arg.startswith("-") and step_owns(step, arg, event)]
    return found


def could_lose_work(edits: list[str], command: str, event: dict) -> bool:
    """Whether these shell writes could change or remove something already there.

    Only one plain command naming paths that aren't there yet can't. A `cd`, a variable, a link made on the way or
    quoting can each change what a path means, so reading the path alone isn't enough to call it new.
    """
    if not edits:
        return False
    if NOT_PLAIN.search(without_heredoc_bodies(command).strip()):
        return True
    cwd = event.get("cwd") or os.getcwd()
    return any(not path or os.path.lexists(os.path.join(cwd, path)) for path in edits)


def is_diff(words: list[str]) -> bool:
    name, args = head(words)
    positional = [arg for arg in args if not arg.startswith("-")]
    return name == "git" and bool(positional) and positional[0] in ("diff", "show", "status")


def pathspecs(text: str, operation: str) -> list[str]:
    """The paths a `git clean`, `restore` or `checkout` names: everything after `--`, or else its words that aren't options or their values."""
    words = text.split()
    after = words[words.index(operation) + 1:] if operation in words else []
    if "--" in after:
        return after[after.index("--") + 1:]
    found, value_next = [], False
    for word in after:
        if value_next:
            value_next = False
        elif word.startswith("-"):
            value_next = word in ("-s", "--source", "-e", "--exclude")
        else:
            found.append(word)
    return found


def _spared(operation: str, text: str, viewed: set[str]) -> bool:
    """A clean of build output only, or a restore of files whose own diff this session looked at first, isn't someone's work going unseen."""
    specs = pathspecs(text, operation)
    if operation == "clean":
        return bool(specs) and all(is_generated(spec) for spec in specs)
    if operation in ("restore", "checkout"):
        return bool(specs) and all(os.path.normpath(spec) in viewed and spec not in (".", "Q") for spec in specs)
    return False


def destructive_git(command: str, viewed: set[str] | None = None) -> str | None:
    """The git operation in this command that can lose work, from what really runs, so a commit message or a grep for the words isn't one.
    `viewed` is the files whose own diff this session has seen."""
    commands = git_commands(command)
    return next((operation for operation, pattern in DESTRUCTIVE_GIT.items() for text in commands if pattern.search(text) and not _spared(operation, text, viewed or set())), None)


_DIFF_HEADER = re.compile(r"^diff --git a/(\S+) b/", re.M)
MAX_DIFF_OUTPUT_READ = 400_000


_SUMMARY_ONLY = {"--stat", "--name-only", "--name-status", "--quiet", "-s", "--no-patch", "--shortstat", "--numstat", "--summary", "--compact-summary",
                 "--dirstat", "--raw"}


def diffs_shown(command: str, output: str, succeeded: bool) -> list[str]:
    """The files a `git diff` here names and whose diff it showed: its output has the file's header, or the diff ended the line and printed
    nothing, which means nothing a restore would discard. A summary, a diff saved to a file and a failed run show none of the changes."""
    if not succeeded:
        return []
    from shell_reading import pipelines

    shown = set(_DIFF_HEADER.findall(output[:MAX_DIFF_OUTPUT_READ]))
    found = []
    for stages in pipelines(command):
        for position, stage in enumerate(stages):
            name, args = head(stage.words)
            if stage.saved or name != "git" or "diff" not in args or any(arg.split("=", 1)[0] in _SUMMARY_ONLY for arg in args):
                continue
            empty = position == len(stages) - 1 and not output.strip()
            found += [path for path in diffed_paths(stage.words) if empty or any(same_file(path, header) for header in shown)]
    return found


def same_file(one: str, other: str) -> bool:
    """The same file, written from the repository's root or from a folder in it."""
    return one == other or one.endswith("/" + other) or other.endswith("/" + one)


def diffed_paths(words: list[str]) -> list[str]:
    """The files a `git diff` names, so a later restore of exactly those can count as looked at first."""
    name, args = head(words)
    if name != "git" or "diff" not in args:
        return []
    specs = pathspecs(" ".join(args), "diff")
    # A file, by its name: a folder holds more than one person's changes, and a glob or a revision range isn't a path
    return [os.path.normpath(spec) for spec in specs if "." in os.path.basename(spec.rstrip("/")) and not spec.endswith("/") and not re.search(r"[*?\[]|\.\.", spec)]


def needs_a_person(command: str, event: dict | None = None) -> str | None:
    text = expand_variables(without_heredoc_bodies(command))
    inside = (lambda path: inside_project(path, event)) if event else (lambda _: False)
    commands = parse_shell(text)[0]
    return evidence.reason_for_a_person(text, [head(words) for words in commands], inside, evidence.in_a_test_environment(commands)) or _reason_from_steps(command, event)


def _sourced(steps: list) -> list[str]:
    return [unquote(step.words[1]) for step in steps if len(step.words) > 1 and head(step.words)[0] in (".", "source")]


# Reading a command again step by step costs as much as the first read, so it happens only when one of these words is there to find.
NAMES_A_SECRET_STORE = re.compile(r"secretsmanager|\bssm\b|\bsecrets?\b|keyvault|\bvault\b|\bop\b|doppler|\bsops\b|\boutput\b", re.I)  # `kubectl get Secret`
NEEDS_THE_STEPS = re.compile(r"python|restor|modify-db|\bg?make\b")


def _reason_from_steps(command: str, event: dict | None) -> str | None:
    """Asks that need each step's own settings, the Python it runs, or a file it names: a secret printed, a restore over production, a download
    run from Python, and a Makefile deleting through a variable it never sets."""
    printed = secret_printed(command) if NAMES_A_SECRET_STORE.search(command) else None
    if printed:
        return f"this prints a secret's value, from {printed}, into the conversation and its logs. Its key names, its length or a hash show what's needed without the value."
    if not NEEDS_THE_STEPS.search(command):
        return None
    steps = read_steps(command)
    sourced_production = any(names_production(path) for path in _sourced(steps))
    for step in steps:
        reason = _step_needs_a_person(step, sourced_production, event)
        if reason:
            return reason
    return None


def _step_needs_a_person(step, sourced_production: bool, event: dict | None) -> str | None:
    secret_file = python_prints_a_secret_file(step.code, lambda path: bool(SECRET_FILE.search(path)))
    if secret_file:
        return f"this prints values from {secret_file}, which holds credentials, into the conversation and its logs. Printing only whether each is set, or its non-secret parts, shows the same."
    if python_runs_a_download(step.code):
        return "this runs code it downloads, without checking where it came from or what it is."
    if not step.words:
        return None
    name, args = head(step.words)
    production = sourced_production or production_target(args) or any(names_production(setting) for setting in settings_of(step.words))
    restore = restore_reason(name, args, production, _restore_script(step, name, args, event) if production else "")
    if restore:
        return restore
    return _make_deletes(step, args, event) if name in ("make", "gmake") and event else None


def _restore_script(step, name: str, args: list[str], event: dict | None) -> str:
    """The text of the restore-named script file this step runs, as `./scripts/restore_latest.sh` or `bash restore.sh`, so what it restores
    can be read when the command doesn't say. Read only that far, and empty when there's none."""
    if not event:
        return ""
    runs_a_file = name in RUNS_A_FILE or re.fullmatch(r"python[\d.]*", name)
    script = next((arg for arg in args if not arg.startswith("-")), "") if runs_a_file else next((unquote(word) for word in step.words if os.path.basename(unquote(word)) == name and "/" in word), "")
    if not script or "restore" not in os.path.basename(script).lower():
        return ""
    return _read_small(Path(event.get("cwd") or os.getcwd(), step.folder or "", os.path.expanduser(script))) or ""


def _make_deletes(step, args: list[str], event: dict) -> str | None:
    folder, makefile, goals, given = _make_arguments(args)
    given |= {setting.split("=", 1)[0] for setting in settings_of(step.words)}
    base = Path(event.get("cwd") or os.getcwd(), step.folder or "", folder)
    for name in ([makefile] if makefile else ["GNUmakefile", "makefile", "Makefile"]):
        path = base / name
        try:
            if path.is_file():
                with path.open(encoding="utf-8", errors="replace") as handle:
                    return make_deletes_through_unset(handle.read(MAX_MAKEFILE_BYTES), goals, given, set_in_environment)
        except OSError:
            return None
    return None


def _make_arguments(args: list[str]) -> tuple[str, str, list[str], set[str]]:
    """What `make` is told: the folder it runs in, the Makefile it reads, the goals, and the variables set on its command line."""
    folder, makefile, goals, given, value_next = "", "", [], set(), ""
    for arg in args:
        if value_next:
            folder, makefile = (arg, makefile) if value_next == "-C" else (folder, arg)
            value_next = ""
        elif arg in ("-C", "--directory", "-f", "--file", "--makefile"):
            value_next = "-C" if arg in ("-C", "--directory") else "-f"
        elif arg.startswith(("--directory=", "--file=", "--makefile=")):
            folder, makefile = (arg.split("=", 1)[1], makefile) if arg.startswith("--directory=") else (folder, arg.split("=", 1)[1])
        elif "=" in arg and not arg.startswith("-"):
            given.add(arg.split("=", 1)[0])
        elif not arg.startswith("-"):
            goals.append(arg)
    return folder, makefile, goals, given


def side_effects(command: str, event: dict) -> list[dict]:
    """Installs and deletions a command made, which a reader of the report needs to hear about."""
    packages = [package for step in shell_steps(command, event) if step.words and not step.elsewhere for package in evidence.installed_packages(*run_by(step.words), INSTALLERS)]
    deleted = [{"name": os.path.basename(path), "path": path} for path in deleted_paths(command, event) if not is_generated(path)]
    return [{"name": package} for package in packages] + deleted


def check_identity(commands: list[list[str]]) -> dict:
    """What each check in this call ran, as [text, key], so runs can be compared. Text is exact, a key is the program and target.

    A script on stdin or in a flag has no identity here: two different ones read alike, and most are one-off probes.
    """
    prefix = [" ".join(words) for words in commands if head(words)[0] in ("cd", "pushd", "source", ".")]
    runs = []
    for words in commands:
        program, args = run_by(words)
        if is_check(words) and args[:1] not in (["-"], ["-c"], ["-e"]):
            key = "python" if re.fullmatch(r"python[\d.]*", program) else program
            target = next((arg for arg in args if not arg.startswith("-")), "")
            runs.append([evidence.redact(" && ".join(prefix + [" ".join(words)]))[:200], evidence.redact(f"{key} {target}".strip())[:200]])
    return {"runs": runs}


# ---------------------------------------------------------------- code downloaded in one call and run in a later one (F266)

CHECKSUM_CHECK = re.compile(r"\b(?:sha(?:1|224|256|384|512)sum|shasum|b2sum|md5sum)\b[^;&|\n]{0,200}(?:\s-c\b|\s--check\b|\s-[a-zA-Z]*c\b)"
                            r"|\bgpg\b[^;&|\n]{0,200}--verify\b|\bcosign[ \t]+verify|\bminisign\b[^;&|\n]{0,100}\s-V\b|\bslsa-verifier\b")
MAX_BUILD_FILE_BYTES = 256_000
OFFICIAL_WRAPPER_HOSTS = {"services.gradle.org", "downloads.gradle.org", "downloads.gradle-dn.com", "repo.maven.apache.org", "repo1.maven.org"}
WRAPPERS = {"gradlew": "gradle/wrapper/gradle-wrapper.properties", "mvnw": ".mvn/wrapper/maven-wrapper.properties"}


def _url_host(args: list[str]) -> str:
    return next((arg.split("/")[2] for arg in args if re.match(r"(?:https?|ftp)://[^/]", arg)), "")


def downloads(command: str, event: dict) -> list[tuple[str, str]]:
    """Files this command saves from the network, as (absolute path, host). One it checks against a checksum or signature in the same command isn't."""
    if not re.search(r"\b(?:curl|wget)\b", command):
        return []
    cwd = event.get("cwd") or os.getcwd()
    found = []
    for step in shell_steps(command, event):
        name, args = head(step.words)
        if name in ("curl", "wget"):
            saved = evidence._saved_as(name, args) + [target for target in step.targets if target and not target.startswith("/dev/")]
            found += [(os.path.normpath(os.path.join(cwd, step.folder or "", os.path.expanduser(path))), _url_host(args)) for path in saved]
    checked = checked_files(command)
    return [(path, host) for path, host in found if os.path.basename(path) not in checked]


_CHECKSUM_SUFFIX = re.compile(r"\.(?:sha(?:1|224|256|384|512)(?:sum)?|md5|b2|asc|sig|minisig)$", re.I)


def checked_files(command: str) -> set[str]:
    """Names of files a command that checks a checksum or a signature mentions, since `echo "HASH  file" | sha256sum -c -` names it before the
    check. `x.sha256` or `x.asc` stands for x."""
    if not CHECKSUM_CHECK.search(command):
        return set()
    names = set(re.findall(r"[\w.+-]+", command))
    return names | {_CHECKSUM_SUFFIX.sub("", name) for name in names}


def files_run(command: str, event: dict) -> list[str]:
    """Files this command runs as programs, absolute: `bash x.sh`, `python3 x.py`, `. ./x`, or `./x` itself."""
    cwd = event.get("cwd") or os.getcwd()
    found = []
    for step in shell_steps(command, event):
        name, args = head(step.words)
        path = _file_a_step_runs(step, name, args) if name else ""
        if path:
            found.append(os.path.normpath(os.path.join(cwd, step.folder or "", os.path.expanduser(path))))
    return found


def _file_a_step_runs(step, name: str, args: list[str]) -> str:
    if name in RUNS_A_FILE or re.fullmatch(r"python[\d.]*", name):
        if any(arg in ("-n", "-c", "-m", "-e") for arg in args):  # a syntax check, inline code or a module
            return ""
        return next((arg for arg in args if not arg.startswith("-")), "")
    return next((unquote(word) for word in step.words if not re.match(r"^\w+=", word) and os.path.basename(unquote(word)) == name and "/" in word), "")


def runs_an_earlier_download(command: str, event: dict, entries: list[dict]) -> str | None:
    """A file an earlier call downloaded, run now with no checksum or signature checked on it in between."""
    unchecked: dict[str, str] = {}
    for entry in entries:
        if entry.get("kind") == "downloaded":
            unchecked[entry.get("path", "")] = entry.get("host") or "the network"
        elif entry.get("kind") == "download_checked":
            unchecked = {path: host for path, host in unchecked.items() if os.path.basename(path) not in entry.get("names", [])}
    if not unchecked:
        return None
    if not re.search(r"\b(?:" + "|".join(re.escape(os.path.basename(path)) for path in list(unchecked)[:50]) + r")\b", command):
        return None
    now_checked = checked_files(command)
    return next((f"this runs {os.path.basename(path)}, which an earlier command downloaded from {unchecked[path]}, and nothing has checked it against a checksum or signature."
                 for path in files_run(command, event) if path in unchecked and os.path.basename(path) not in now_checked), None)


def _at_head(event: dict, path: Path) -> str | None:
    """The file as the last commit has it, cut one character past MAX_BUILD_FILE_BYTES so a caller can tell it was cut, or None if it wasn't
    there or git can't say."""
    try:
        from occam_tools.files import run_git

        root = project_root(event)
        text = run_git(root, "show", f"HEAD:{os.path.relpath(path, os.path.realpath(root))}", timeout=5)
        return None if text is None else text[:MAX_BUILD_FILE_BYTES + 1]
    except Exception:  # occam: ignore[swallowed-exception] a check that can't run says nothing
        return None


def _read_small(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BUILD_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _joined_lines(text: str) -> list[str]:
    """A Dockerfile's lines with backslash continuations joined, so a multi-line RUN is one line."""
    return re.sub(r"\\\n", " ", text).split("\n")


MAX_BUILD_FILES_READ = 20  # distinct Dockerfiles or wrapper settings one command is read for, since each can cost a `git show`


def build_runs_a_new_download(command: str, event: dict) -> str | None:
    """An image build whose Dockerfile has a RUN step, not in the last commit, piping a download into a shell. The build is when it runs,
    so it's asked each time. A Dockerfile already read for an earlier step in this command says the same again."""
    if not re.search(r"\b(?:docker|podman|buildah)\b[^\n;&|]{0,300}\bbuild\b", command):
        return None
    cwd = event.get("cwd") or os.getcwd()
    read: set[Path] = set()
    for step in shell_steps(command, event):
        dockerfile = _dockerfile_built(step, cwd)
        if dockerfile is None or dockerfile in read or len(read) >= MAX_BUILD_FILES_READ:
            continue
        read.add(dockerfile)
        text = _read_small(dockerfile)
        run = _new_step_running_a_download(text, dockerfile, event) if text else None
        if run:
            host = _url_host(run.replace("'", " ").replace('"', " ").split()) or "the network"
            return (f"this builds an image whose new step `{run[:120]}` runs a script from {host} straight in a shell, unpinned and unchecked, "
                    "and the image keeps what it installed.")
    return None


_BUILD_TAKES_A_VALUE = ("-f", "--file", "-t", "--tag", "--target", "--build-arg", "--platform", "--secret", "--cache-from", "-o", "--output", "--label")


def _dockerfile_built(step, cwd: str) -> Path | None:
    """The Dockerfile an image build reads: the one `-f` names, or the context's own. None when the step isn't an image build."""
    name, args = head(step.words)
    if name not in ("docker", "podman", "buildah") or "build" not in args[:3] or "compose" in args[:1]:
        return None
    rest = args[args.index("build") + 1:]
    plain = [arg for index, arg in enumerate(rest) if not arg.startswith("-") and (index == 0 or rest[index - 1] not in _BUILD_TAKES_A_VALUE)]
    context = Path(cwd, step.folder or "", plain[-1] if plain else ".")
    given = option_value(rest, ("-f", "--file"))
    return Path(cwd, step.folder or "", given) if given else context / "Dockerfile"


def _new_step_running_a_download(text: str, dockerfile: Path, event: dict) -> str | None:
    """The first RUN step piping a download into a shell that the last commit's Dockerfile doesn't have. The commit is read once, and only
    when there's such a step; when it's past what's read, which steps are new can't be told."""
    committed = None
    for line in _joined_lines(text):
        run = line.strip()
        if not re.match(r"RUN\b", run, re.I) or not _pipes_a_download(run):
            continue
        if committed is None:
            before = _at_head(event, dockerfile.resolve()) or ""
            if len(before) > MAX_BUILD_FILE_BYTES:
                return None
            committed = {old.strip() for old in _joined_lines(before)}
        if run not in committed:
            return run
    return None


def _pipes_a_download(run: str) -> bool:
    return bool(evidence.PIPE_TO_SHELL.search(re.sub(r"'[^']*'|\"[^\"]*\"", "''", run)) or evidence.SHELL_RUNS_DOWNLOAD.search(run))


def wrapper_moved(command: str, event: dict) -> str | None:
    """`./gradlew` or `./mvnw` after this work pointed the wrapper at a host that isn't Gradle's or Maven's own, with no checksum: the run
    downloads that distribution and runs it."""
    if not re.search(r"\b(?:gradlew|mvnw)\b", command):
        return None
    cwd = event.get("cwd") or os.getcwd()
    read: set[Path] = set()  # a wrapper already read for an earlier step says the same again
    for step in shell_steps(command, event):
        name, args = head(step.words)
        properties = Path(cwd, step.folder or "", option_value(args, ("-p", "--project-dir")) if name == "gradlew" else "") / WRAPPERS[name] if name in WRAPPERS else None
        if properties is None or properties in read or len(read) >= MAX_BUILD_FILES_READ:
            continue
        read.add(properties)
        host = _host_a_wrapper_moved_to(properties, event)
        if host is not None:
            return (f"this runs {name}, which downloads the build tool from {host} and runs it. This work pointed the wrapper there, away from where the last commit had it, "
                    "and there's no distributionSha256Sum to check what arrives.")
    return None


def _host_a_wrapper_moved_to(properties: Path, event: dict) -> str | None:
    """The host a wrapper's properties now download from, when that isn't an official one, there's no checksum, and the last commit had it elsewhere."""
    text = _read_small(properties)
    url = re.search(r"^distributionUrl\s*=\s*(\S+)", text or "", re.M)
    if not url:
        return None
    address = url.group(1).replace("\\:", ":")
    host = address.split("/")[2] if address.count("/") >= 2 else address
    before = _at_head(event, properties.resolve())
    if host in OFFICIAL_WRAPPER_HOSTS or re.search(r"^distributionSha256Sum\s*=\s*\S", text or "", re.M) or before is None or url.group(0) in before:
        return None
    return host


def viewed_files(entries: list) -> set[str]:
    """Files whose own diff this session has looked at since it last changed them."""
    viewed: set[str] = set()
    for entry in entries:
        if entry.get("kind") == "diff":
            viewed.update(entry.get("paths") or [])
        elif entry.get("kind") == "edit" and entry.get("path"):
            edited = os.path.normpath(entry["path"])
            viewed = {path for path in viewed if not same_file(path, edited)}
    return viewed


def runs_unchecked_downloads(command: str, event: dict, entries: list) -> str | None:
    """The owner's ask for running downloaded code (2026-11-07), across calls: a file an earlier call fetched, an image build running a new
    `curl | sh` step, and a build wrapper this work pointed at another host. Each is asked on every attempt, as the other asks are."""
    return runs_an_earlier_download(command, event, entries) or wrapper_moved(command, event) or build_runs_a_new_download(command, event)


# What a check prints when it ran: a count, or a checker's own summary. Not a bare "ok", which `; echo ok` prints whether or not the
# check ran. `go vet` and `tsc` print nothing when they pass, which is fine when nothing could have skipped them.
_RAN = re.compile(r"\b(?:passed|passing|all checks passed|no (?:issues|errors|problems) found|success: no issues|0 (?:errors|failures|problems))\b", re.I)
# What an `&&` chain is built to stop at: a test that's expected to fail sometimes. `cd x && pytest` or `source env && pytest` is setup,
# which normally succeeds, so what follows it ran.
_GUARDS = {"test", "[", "[[", "false", "command", "which", "type", "hash"}


def _guards(words: list[str]) -> bool:
    name = os.path.basename(words[0]) if words else ""
    return name in _GUARDS or (name in ("grep", "egrep", "fgrep", "rg") and any(word in ("-q", "--quiet", "-s") for word in words)) or (
        name == "git" and any(word in ("--quiet", "-q", "--exit-code") for word in words))


def may_have_skipped(step: Any, steps: list, event: dict) -> bool:
    """A check in an if, case or loop body or a function, after `||`, or after a test in an `&&` chain that something else runs after,
    may not have run however the command ended. Unless its output shows it did, it isn't evidence: `if false; then pytest; fi` exits 0."""
    output = output_text(event.get("tool_response")) + "\n" + str(event.get("error") or "")
    if evidence.shows_a_count(output) or _RAN.search(output[-8000:]):
        return False
    if step.branch or step.joined == "||":
        return True
    index = next(index for index, each in enumerate(steps) if each is step)
    return step.joined == "&&" and index > 0 and _guards(steps[index - 1].words) and any(each.joined not in ("&&", "|") for each in steps[index + 1:])


def _state_of(event: dict, path: str) -> list | None:
    try:
        info = os.stat(os.path.join(event.get("cwd") or "", path))
    except OSError:
        return None
    return [info.st_size, info.st_mtime_ns]


def note_targets(event: dict, edits: list[str]) -> None:
    """Before a command runs, the state of the files it may write. Exiting nonzero undoes nothing, so `printf x > app.py; false`
    has changed app.py, and comparing afterwards shows which writes happened."""
    if event.get("tool_use_id") and any(edits):
        record(event, kind="before_shell", id=event["tool_use_id"], files={path: _state_of(event, path) for path in edits if path})


def written_anyway(event: dict, paths: list[str]) -> list[str]:
    """Of the paths a failed command may have written, the ones that changed while it ran. Without a note from before, none."""
    before = next((entry["files"] for entry in reversed(Session(event).turn) if entry.get("kind") == "before_shell" and entry.get("id") == event.get("tool_use_id")), None)
    if not event.get("tool_use_id") or not isinstance(before, dict):
        return []
    return [path for path in paths if path in before and _state_of(event, path) != before[path]]
