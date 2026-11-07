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
from occam_commands import INSTALLERS, golden_command, head, is_check, nbconvert_target, rewrites_in_place, run_by, unquote, writes_project_files
from shell_reading import expand_variables, git_commands, parse_shell, python_writes, read_steps, without_heredoc_bodies

TEMP_VARIABLES = {"TMPDIR", "TMP", "TEMP", "HOME"}
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
    "restore": re.compile(GIT + r"restore\s(?![^;&|]*--staged)"),
    "clean": re.compile(GIT + r"clean\b[^;&|]*\s-[a-zA-Z]*f"),
    "stash": re.compile(GIT + r"stash\b(?!\s+(?:list|show)\b)"),
    "push": re.compile(GIT + r"push\b[^;&|]*(?:--force|\s-f\b)"),
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


def inside_project(path: str, event: dict) -> bool:
    """Under the project or the working directory, and not one of them, so deleting it can't take the whole thing."""
    roots = [os.path.realpath(root) for root in (event.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")) if root]
    real = os.path.realpath(path)
    return real not in roots and in_project(path, event)


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


def shell_steps(command: str, event: dict) -> list:
    return read_steps(command, lambda place: leaves_project(place, event, command))


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
        for path in paths:
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


def destructive_git(command: str) -> str | None:
    """The git operation in this command that can lose work, from what really runs, so a commit message or a grep for the words isn't one."""
    commands = git_commands(command)
    return next((operation for operation, pattern in DESTRUCTIVE_GIT.items() for text in commands if pattern.search(text)), None)


def needs_a_person(command: str, event: dict | None = None) -> str | None:
    text = expand_variables(without_heredoc_bodies(command))
    inside = (lambda path: inside_project(path, event)) if event else (lambda _: False)
    return evidence.reason_for_a_person(text, [head(words) for words in parse_shell(text)[0]], inside)


def side_effects(command: str, event: dict) -> list[dict]:
    """Installs and deletions a command made, which a reader of the report needs to hear about."""
    packages = [package for step in shell_steps(command, event) if step.words and not step.elsewhere for package in evidence.installed_packages(*run_by(step.words), INSTALLERS)]
    deleted = [{"name": os.path.basename(path), "path": path} for path in deleted_paths(command, event) if not evidence.is_generated(path)]
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
