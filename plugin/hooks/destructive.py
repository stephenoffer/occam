"""Commands that are hard to undo, and how far a delete or a restore reaches: the listed destructive spellings, a store or bucket emptied,
a recursive delete through a path nothing checked, a Makefile deleting through a variable it never sets, and a restore over production.
Each gives why a person should confirm the command, or nothing. A person confirms these by the owner's decisions of 2026-11-06 and 2026-11-07.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import os
import re
from typing import Callable

from occam_commands import RUNS_A_FILE, option_value, subcommand


# Each incident on record began with one of these run on a guess. A program's entry lists words that must all appear in its arguments.
_TERRAFORM = (("destroy",), ("apply", "-auto-approve"), ("apply", "--auto-approve"), ("state", "rm"), ("state", "push"))
_RAILS = (("db:drop",), ("db:reset",), ("db:schema:load",))
_PRISMA = (("migrate", "reset"), ("--force-reset",), ("--accept-data-loss",))
HARD_TO_UNDO = {"terraform": _TERRAFORM, "tofu": _TERRAFORM, "terragrunt": _TERRAFORM, "pulumi": (("destroy",),), "kubectl": (("delete",),), "helm": (("uninstall",), ("delete",), ("del",), ("un",)),
                "gcloud": (("delete",),), "az": (("delete",),), "doctl": (("delete",),), "fly": (("destroy",),), "flyctl": (("destroy",),), "heroku": (("apps:destroy",), ("pg:reset",)), "vercel": (("remove",), ("rm",)),
                "railway": (("down",), ("delete",)), "supabase": (("db", "reset"),), "prisma": _PRISMA, "rails": _RAILS, "rake": _RAILS, "dropdb": ((),), "mongorestore": (("--drop",),),
                "docker": (("system", "prune"), ("volume", "rm"), ("volume", "prune"), ("compose", "down", "-v"), ("compose", "down", "--volumes")), "docker-compose": (("down", "-v"), ("down", "--volumes"))}
_RUNS_ANOTHER_PROGRAM = {"bundle", "pnpm", "yarn", "npx", "bunx", "uv", "poetry"}
# `help` counts only as the subcommand, and `-h` never: for redis-cli, dropdb and psql it names a host. A dry run says so with a value that means it.
_ONLY_LOOKS = re.compile(r"--help|--dry-?run(?:=(?:client|server|true|all))?|--preview-only", re.I)
_SUBCOMMAND_MUST_BE = {"kubectl": ("delete",), "helm": ("uninstall", "delete", "del", "un")}
_AWS_DESTRUCTIVE = re.compile(r"(?:delete|terminate|deregister|purge)-[\w-]+")
# A flag cluster holding r or R, with those left out of what comes before, as occam_commands' IN_PLACE does: the first r is then the one,
# so a long cluster without one is read once rather than from every position.
RECURSIVE_FLAG = re.compile(r"-[a-qs-zA-QS-Z]*[rR][a-zA-Z]*")
_TEMPORARY = re.compile(r"(?:^|_)(?:te?mp(?:dir)?|scratch)(?:_|$)", re.I)  # TMPDIR, RUNNER_TEMP, tmp_dir, and not TEMPLATE_DIR
# Variables this command sets itself, by substitution, a loop or read, which expand_variables can't resolve but which aren't unset.
# A prefix assignment, as `OUT=build make`, sets the variable for that one program only, so it doesn't count.
_ASSIGNED = re.compile(r"(?:^|[;&|(\n])[ \t]*(?:export[ \t]+|local[ \t]+|declare[ \t]+)?([A-Za-z_]\w*)=(?:\"[^\"\n]{0,500}\"|'[^'\n]{0,500}'|\$\([^()\n]{0,500}\)|`[^`\n]{0,500}`|[^\s;&|()]{0,500})[ \t]*(?=$|[;&|)\n])"
                       r"|\bfor[ \t]+([A-Za-z_]\w*)[ \t]+in\b|\bread[ \t]+(?:-\w+[ \t]+)*([A-Za-z_]\w*)")
_PG_RESTORE_VALUES = set("dfFhpUILnNPStTj")  # pg_restore's short options that take a value, joined or next
GENERATED_NAMES = {"build", "dist", "target", "out", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
                   ".venv", "venv", ".next", ".cache", ".turbo", ".gradle", "coverage", ".coverage", "htmlcov", "test-results"}


def is_generated(path: str) -> bool:
    return os.path.basename(path.rstrip("/*")) in GENERATED_NAMES


def deletes_too_much(word: str, inside_project=lambda _: False) -> bool:
    """Would a recursive delete of this reach the root, home, the whole working directory, or outside it?

    A folder in the project written as an absolute path is the same delete as `rm -rf src`, which isn't asked about.
    """
    if not word:
        return False
    bare = word.replace('"', "").replace("'", "")  # `"$HOME/"*` is $HOME's contents
    if bare == "$" or bare.startswith(("$(", "`", "$PWD", "${PWD", "$HOME", "${HOME", "~")):
        return True
    if bare.startswith("$"):  # a word mixing quotes and a glob, as in "$DIR/"*, keeps its quotes here
        return unset_variable(word) is not None
    path = os.path.normpath(word)
    if word in ("*", "./*", "../*", "/*") or path in (".", "..", "/") or path.startswith("../"):
        return True
    if not path.startswith("/"):
        return False
    place = inside_project(path)
    if place is None:  # the project or a folder holding it, even in a temp folder
        return True
    if place or path.startswith(("/tmp/", "/private/tmp/", "/var/folders/")):
        return False
    return not is_generated(path)


# `[ -n "$X" ]` guards only what its `&&` chain runs, so it counts with one after it, or with `|| exit`, and `[ -z "$X" ]` with `&& exit`.
_GUARDS = re.compile(r"\$\{([A-Za-z_]\w*):?\?|(?:\[\[?|\btest)[ \t]+-n[ \t]+[\"']?\$\{?([A-Za-z_]\w*)\}?[\"']?[ \t]*(?:\]\]?[ \t]*)?(?:&&|\|\|[ \t]*(?:exit|return)\b)"
                     r"|-z[ \t]+[\"']?\$\{?([A-Za-z_]\w*)\}?[\"']?[ \t]*(?:\]\]?[ \t]*)?&&[ \t]*(?:exit\b|return\b|\{)")


def guarded_names(text: str) -> set[str]:
    """Variables this command stops on when empty: `${X:?}`, `[ -n "$X" ]`, or `[ -z "$X" ] && exit`. One pass, whatever the number of variables."""
    return {name for groups in _GUARDS.findall(text) for name in groups if name}


def bucket_reach(args: list[str], guards: set[str]) -> str | None:
    """What a bucket delete reaches, when that's the whole bucket, by its root or a wildcard over everything, or a path a variable decides."""
    url = next((arg for arg in args if arg.lower().startswith(("s3://", "gs://"))), None)
    if url is None:
        return "a path it doesn't name"
    key = url.split("/", 3)[3] if url.count("/") >= 3 else ""
    if not key.strip("/*"):
        return f"{url}, the whole bucket"
    for variable, modifier in re.findall(r"\$\{?([A-Za-z_]\w*)(:?\?)?", key):
        if not modifier and variable not in guards and not _TEMPORARY.search(variable):
            return f"{url}, which reaches the whole bucket or a wider prefix if {variable} is empty"
    return None


def _empties_a_store(name: str, lowered: list[str], args: list[str] | None = None, guards: frozenset | set = frozenset()) -> str | None:
    """The commands whose danger is in their arguments' shape rather than in a fixed subcommand. Each check is asked in turn: None passes
    to the next, and an empty reason means the command is that check's and isn't asked about."""
    args = lowered if args is None else args
    for check in _STORE_CHECKS:
        found = check(name, lowered, args, guards)
        if found is not None:
            return found or None
    return None


def _s3_recursive_delete(name: str, lowered: list[str], args: list[str], guards: frozenset | set) -> str | None:
    """Asked about whatever the prefix, as before this work: nothing brings back what it deletes."""
    if name != "aws" or not {"s3", "rm", "--recursive"} <= set(lowered) or "--dryrun" in lowered:
        return None
    reach = bucket_reach(args, guards)
    return f"this recursively deletes {reach}." if reach else "this `aws` command is hard to undo."


def _bucket_delete(name: str, lowered: list[str], args: list[str], guards: frozenset | set) -> str | None:
    """gsutil's and gcloud's deletes: a literal prefix is as scoped as `rm -rf build/`, and without -r only a wildcard reaches everything."""
    if not ((name == "gsutil" and "rm" in lowered) or (name == "gcloud" and lowered[:2] == ["storage", "rm"])):
        return None
    recursive = any(arg in ("--recursive", "-r") or RECURSIVE_FLAG.fullmatch(arg) for arg in args)
    reach = bucket_reach(args, guards)
    return f"this deletes {reach}." if reach and (recursive or reach.endswith("the whole bucket")) else ""


def _aws_destroys(name: str, lowered: list[str], args: list[str], guards: frozenset | set) -> str | None:
    if name == "aws" and (any(_AWS_DESTRUCTIVE.fullmatch(arg) for arg in lowered) or ("s3" in lowered and "rb" in lowered)):
        return "this `aws` command is hard to undo."
    return None


def _flushes(name: str, lowered: list[str], args: list[str], guards: frozenset | set) -> str | None:
    """`redis-cli flushall` and `manage.py flush`, which empty the database."""
    if name == "redis-cli" and lowered[-1:] in (["flushall"], ["flushdb"]) and lowered[-2:-1] not in (["get"], ["set"], ["del"], ["exists"], ["type"]):
        return f"`redis-cli {lowered[-1]}` empties the database."
    if any(os.path.basename(arg) == "manage.py" and lowered[index + 1:index + 2] == ["flush"] for index, arg in enumerate(lowered)):
        return "`manage.py flush` empties the database."
    return None


# How a sync says it deletes what the source lacks, and that it's only a trial: the program, the words it starts with, and those two flags.
# gsutil takes its flags as letters after `rsync`, as `rsync -d -n` or `rsync -dn`.
_SYNCS = {("aws", ("s3", "sync")): ("--delete", "--dryrun"), ("gcloud", ("storage", "rsync")): ("--delete-unmatched-destination-objects", "--dry-run")}


def _sync_flags(name: str, lowered: list[str]) -> tuple[bool, bool] | None:
    """Whether this sync deletes what the source doesn't have, and whether it's a dry run, or None when it isn't one of these syncs."""
    if name == "gsutil" and "rsync" in lowered:
        letters = "".join(arg[1:] for arg in lowered[lowered.index("rsync") + 1:] if re.fullmatch(r"-[a-z]+", arg))
        return "d" in letters, "n" in letters
    flags = _SYNCS.get((name, tuple(lowered[:2])))
    return (flags[0] in lowered, flags[1] in lowered) if flags else None


def _syncs_away(name: str, lowered: list[str], args: list[str], guards: frozenset | set) -> str | None:
    """`aws s3 sync --delete`, `gsutil rsync -d` and `gcloud storage rsync --delete-unmatched-destination-objects` make the destination match
    the source, so into a bucket's root, or a prefix a variable decides, they delete everything else there."""
    flags = _sync_flags(name, lowered)
    if flags is None:
        return None
    deletes, dry = flags
    buckets = [arg for arg in args if arg.lower().startswith(("s3://", "gs://"))]
    if not deletes or dry or not buckets or buckets[-1] != [arg for arg in args if not arg.startswith("-")][-1]:
        return None  # into a local folder, a mirror of the bucket that this work made
    reach = bucket_reach([buckets[-1]], guards)
    return f"this mirrors into {reach}, deleting everything there the source doesn't have." if reach else None


_STORE_CHECKS = (_s3_recursive_delete, _bucket_delete, _syncs_away, _aws_destroys, _flushes)


def _restores_over(args: list[str]) -> bool:
    """pg_restore's -c or --clean drops what the database holds first. Writing a script with -f, and naming no database, touches nothing."""
    flags = set()
    for cluster in (arg[1:] for arg in args if arg.startswith("-") and not arg.startswith("--")):
        for letter in cluster:  # letters up to and including one that takes a value, whose value is the rest: `-Fc` is a format
            flags.add(letter)
            if letter in _PG_RESTORE_VALUES:
                break
    clean = "--clean" in args or "c" in flags
    database = any(arg == "--dbname" or arg.startswith("--dbname=") for arg in args) or "d" in flags
    script = any(arg == "--file" or arg.startswith("--file=") for arg in args) or "f" in flags
    return clean and (database or not script)


def _run_inside(name: str, args: list[str]) -> tuple[str, list[str]] | None:
    """The program a container's `exec` runs, when it's one this file knows, with its own arguments. What runs inside is what matters."""
    lowered = [arg.lower() for arg in args]
    if name not in ("docker", "docker-compose", "podman", "kubectl") or "exec" not in lowered:
        return None
    inner = next((index for index, arg in enumerate(lowered) if index > lowered.index("exec") and (arg in HARD_TO_UNDO or arg == "pg_restore")), None)
    return (lowered[inner], args[inner + 1:]) if inner is not None else None


def hard_to_undo(name: str, args: list[str], testing: bool = False, guards: frozenset | set = frozenset()) -> str | None:
    """Why this one program needs a person first, when it's on the list of commands that are hard to undo or empties a store."""
    inside = _run_inside(name, args)
    if inside:
        return hard_to_undo(*inside, testing, guards)
    if name == "pg_restore":
        return "`pg_restore --clean` is hard to undo." if _restores_over(args) else None
    lowered = [arg.lower() for arg in args]
    if any(_ONLY_LOOKS.fullmatch(arg) for arg in args) or lowered[:1] == ["help"]:
        return None
    return _empties_a_store(name, lowered, args, guards) or _listed_hard_to_undo(name, lowered, testing)


def _listed_hard_to_undo(name: str, lowered: list[str], testing: bool) -> str | None:
    """A program HARD_TO_UNDO lists, run directly or through a runner such as npx, with the words that make it so."""
    program = _listed_program(name, lowered)
    if program is None or (program == "gcloud" and lowered[:1] == ["config"]) or (program in ("rails", "rake", "prisma") and testing):
        return None
    if program in _SUBCOMMAND_MUST_BE and not _its_subcommand_is_listed(name, program, lowered):
        return None
    words = next((words for words in HARD_TO_UNDO[program] if all(word in lowered for word in words)), None)
    return f"`{' '.join((program, *words))}` is hard to undo." if words is not None else None


def _listed_program(name: str, lowered: list[str]) -> str | None:
    return name if name in HARD_TO_UNDO else next((arg for arg in lowered if arg in HARD_TO_UNDO), None) if name in _RUNS_ANOTHER_PROGRAM else None


def _its_subcommand_is_listed(name: str, program: str, lowered: list[str]) -> bool:
    after = lowered[lowered.index(program) + 1:] if name != program else lowered  # `npx kubectl delete` is kubectl's own words after its name
    return "-h" not in after and (subcommand(program, after) or "") in _SUBCOMMAND_MUST_BE[program]


def assigned_names(text: str) -> set[str]:
    """Variables this command sets itself, by substitution, a loop or read, which aren't unset however they read."""
    return {found for groups in _ASSIGNED.findall(text) for found in groups if found}


def deletes_too_much_of(args: list[str], text: str, inside_project, assigned: set[str] | None = None) -> str | None:
    """Why a recursive rm needs a person, if it does. A variable this command sets itself, as `D=$(mktemp -d)` or a loop's, isn't unset."""
    if assigned is None:
        assigned = assigned_names(text)
    targets = [arg for arg in args if not arg.startswith("-") and deletes_too_much(arg, inside_project) and unset_variable(arg) not in assigned]
    if not targets:
        return None
    unset = unset_variable(targets[0])
    return f"this recursively deletes {targets[0]}" + (f", which is from the root if {unset} is empty or unset." if unset else ".")


def unset_variable(word: str) -> str | None:
    """The variable a delete target starts with, then a path, when nothing guards it: `$DIR/x`, `${DIR:-}/x`, `$1/x`. `rm -rf $DIR` alone
    deletes nothing when DIR is empty, so it isn't one."""
    return empty_path_variable(word, alone=False)


# ---------------------------------------------------------------- deletes through a path nothing checked (F265, the owner's ask of 2026-11-07)

# `$DIR/`, `${DIR}/`, `${DIR:-}/` and `$1/` are the root when the variable is empty. `${DIR:?}` and `${DIR?}` stop the shell first, and
# `${DIR:-build}` or `${DIR:=build}` can't be empty.
_VARIABLE_PATH = re.compile(r"^\$(?:\{([A-Za-z_]\w*(?!\w)|\d+(?!\d))([^}]*)\}|([A-Za-z_]\w*|\d))(/.*)?$")  # a name gives nothing back to what follows it
_DIRNAME_OF = re.compile(r"^\$\(\s*dirname\s+(?:--\s+)?[\"']?(\$\{?[A-Za-z_]\w*\}?)[\"']?\s*\)$")
_SHARED_FOLDER = re.compile(r"^(?:/(?:var|srv|opt|home|usr|usr/local|usr/share|etc|data|mnt|media|var/lib|var/www|Users|Library|Volumes|root|tmp|private/tmp)?"
                            r"|~|\$HOME|\$\{HOME\}|/(?:home|Users)/[^/]+)$")  # the project itself is this work's, as `rm -rf build` is
_RSYNC_TAKES_A_VALUE = {"-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--files-from", "--exclude-from", "--include-from", "--chmod", "--chown", "--password-file",
                        "--backup-dir", "--partial-dir", "-T", "--temp-dir", "--compare-dest", "--copy-dest", "--link-dest", "--log-file", "--out-format", "-M", "--remote-option",
                        "--port", "--rsync-path", "--timeout", "--contimeout", "--bwlimit", "--max-size", "--min-size", "-B", "--block-size", "--suffix", "--usermap", "--groupmap"}
# A cleanup script told not to ask, as `purge_cache.py --root "$X" --yes`, deletes whatever that root turns out to be.
_DELETES_BY_NAME = re.compile(r"(?:^|[_.-])(?:purge|clean|cleanup|wipe|delete|remove|prune|nuke|reset|clear|destroy)(?:[_.-]|$)", re.I)
_SKIPS_CONFIRMATION = {"--yes", "-y", "--force", "-f", "--assume-yes", "--no-confirm", "--noconfirm", "--no-input", "--noinput"}


def empty_path_variable(word: str, assigned: set[str] = frozenset(), alone: bool = True, known=lambda _: False) -> str | None:
    """The variable that makes this path the root when it's empty or unset, as `$DIR/x`, `${DIR:-}/x` and `$1/x` do. With `alone`, also
    `$DIR` and `$(dirname "$F")`, which find, rsync and most scripts read as the current folder.
    One this command sets itself (`assigned`), one `known` to be set, a default, a `:?` stop, or a temp folder's set by the system isn't.
    $PWD and $HOME are asked about for what they always hold."""
    dirname = _DIRNAME_OF.match(word) if alone else None
    found = _VARIABLE_PATH.match((dirname.group(1) if dirname else word).replace('"', "").replace("'", ""))
    if not found or not (alone or found.group(4)):
        return None
    name, modifier = found.group(1) or found.group(3), found.group(2) or ""
    defaulted = re.match(r":?[-=].", modifier) is not None  # `${DIR:-build}` has a value either way, and `${DIR:-}` doesn't
    if modifier.startswith((":?", "?")) or defaulted or _TEMPORARY.search(name) or name in ("PWD", "HOME", "0") or name in assigned or known(name):
        return None
    return name


def set_in_environment(name: str) -> bool:
    """Set, and not empty, where this runs: the shell the command runs in starts from the same environment."""
    return os.environ.get(name, "") != ""


_XARGS_TAKES_A_VALUE = {"-n", "-I", "-P", "-d", "-L", "-s", "-E", "-a", "--max-args", "--max-procs", "--delimiter", "--max-lines", "--arg-file"}


def xargs_program(args: list[str]) -> str:
    """The program xargs runs, past its own options."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in _XARGS_TAKES_A_VALUE else 1
    return os.path.basename(args[index]) if index < len(args) else "echo"


def find_piped_to_a_delete(text: str, assigned: set[str]) -> str | None:
    """`find $ROOT ... | xargs rm`: what find lists, from the current folder when ROOT is empty, is what's deleted."""
    from occam_commands import head
    from shell_reading import pipelines

    for stages in pipelines(text):
        for before, after in zip(stages, stages[1:]):
            (name, args), (then, rest) = head(before.words), head(after.words)
            if name == "find" and then == "xargs" and xargs_program(rest) in ("rm", "unlink", "shred"):
                found = _find_deletes_from_unset(args, assigned, deletes=True)
                if found:
                    return found
    return None


def _find_deletes_from_unset(args: list[str], assigned: set[str], deletes: bool = False) -> str | None:
    """`find $ROOT -delete` with ROOT empty searches from the current folder, which GNU find does when given no path. `deletes` says a
    later stage deletes what it lists."""
    deletes = deletes or "-delete" in args or any(arg in ("-exec", "-execdir", "-ok") and os.path.basename(args[index + 1]) in ("rm", "unlink", "shred")
                                                  for index, arg in enumerate(args[:-1]))
    if not deletes:
        return None
    for root in args:
        if root.startswith(("-", "(", "!")):  # the paths come before the first expression word
            break
        variable = empty_path_variable(root, assigned, known=set_in_environment)
        if variable:
            return f"this deletes what find matches under {root}, which is the current folder or the root if {variable} is empty or unset."
    return None


def _rsync_reaches_too_far(args: list[str], assigned: set[str]) -> str | None:
    """`rsync --delete` makes the destination match the source, so into a folder other things share it deletes them."""
    plain = _rsync_paths(args) if _rsync_deletes(args) else []
    if len(plain) < 2:
        return None
    remote = re.match(r"^(?:[\w.-]+@)?[\w.-]{2,}:(?!//)(.*)$", plain[-1])
    path = (remote.group(1) or "~") if remote else plain[-1]
    if _SHARED_FOLDER.match(path.rstrip("/") or "/") or empty_path_variable(path, assigned, known=set_in_environment):
        return f"this mirrors {plain[-2]} into {plain[-1]} with --delete, so everything else in that folder, which other things share, is deleted."
    return None


def _rsync_deletes(args: list[str]) -> bool:
    """With --delete or one of its kinds, and not a dry run."""
    deletes = any(arg in ("--delete", "--del") or arg.startswith(("--delete-", "--delete=")) for arg in args)
    return deletes and "--dry-run" not in args and not any(re.fullmatch(r"-[a-mo-zA-Z]*n[a-zA-Z]*", arg) for arg in args)


def _rsync_paths(args: list[str]) -> list[str]:
    """The source and destination words, past options and the values some of them take."""
    plain, value_next = [], False
    for arg in args:
        if value_next:
            value_next = False
        elif arg.startswith("-"):
            value_next = arg in _RSYNC_TAKES_A_VALUE
        else:
            plain.append(arg)
    return plain


# Programs that delete through a path they're given, read with what this command assigns.
_DELETES_THROUGH = {"find": lambda name, args, assigned: _find_deletes_from_unset(args, assigned), "rsync": lambda name, args, assigned: _rsync_reaches_too_far(args, assigned)}


def deletes_through_unset(name: str, args: list[str], assigned: Callable[[], set[str]]) -> str | None:
    """A delete through a path this command never sets: find's root, rsync's destination, or the folder a cleanup script is told not to ask
    about. `assigned` gives what the command sets, read the first time it's needed."""
    deletes = _DELETES_THROUGH.get(name, _script_deletes_from_unset if set(args) & _SKIPS_CONFIRMATION else None)
    return deletes(name, args, assigned()) if deletes else None


def _script_deletes_from_unset(name: str, args: list[str], assigned: set[str]) -> str | None:
    script = next((arg for arg in args if not arg.startswith("-")), "") if name in RUNS_A_FILE or re.fullmatch(r"python[\d.]*", name) else name
    if not _DELETES_BY_NAME.search(os.path.basename(script).rsplit(".", 1)[0]) or not set(args) & _SKIPS_CONFIRMATION:
        return None
    for arg in args:
        value = arg.split("=", 1)[1] if arg.startswith("--") and "=" in arg else arg
        variable = empty_path_variable(value, assigned, known=set_in_environment)
        if variable:
            return f"this runs {os.path.basename(script)} without asking on {value}, which is the current folder or the root if {variable} is empty or unset."
    return None


# ---------------------------------------------------------------- a Makefile recipe deleting through a variable it never sets (F265)

MAX_MAKEFILE_BYTES = 256_000
MAX_GOALS_READ = 20
_MAKE_ASSIGNS = re.compile(r"^(?:(?:export|override|private)[ \t]+)*([A-Za-z_][\w.-]*)[ \t]*(?:\?|:{1,3}|\+|!)?=")
_MAKE_RULE = re.compile(r"^([^:=\s#][^:=#]*)::?(?!=)(.*)$")  # greedy to the first colon: the targets are split on spaces anyway
_MAKE_RM = re.compile(r"(?:^|[\s;&|(@-])rm[ \t]+(?:-[a-qs-zA-QS-Z]*[rR][a-zA-Z]*|--recursive)[ \t]+(?:-\S+[ \t]+)*[\"']?\$[({]([A-Za-z_][\w.-]*)[)}]/")
_MAKE_CONDITIONAL = re.compile(r"[ \t]*(?:ifeq|ifneq|ifdef|ifndef|else|endif)\b")
_MAKE_BUILTINS = {"CURDIR", "MAKE", "MAKEFLAGS", "MAKEFILE_LIST", "MAKECMDGOALS", "SHELL", "MAKELEVEL", "RM", ".DEFAULT_GOAL"}


def make_deletes_through_unset(makefile: str, goals: list[str], given: set[str], known=lambda _: False) -> str | None:
    """Why `make GOAL` needs a person: its recipe runs `rm -rf $(VAR)/...` and nothing sets VAR, so make expands it to nothing.
    A Makefile that includes another can set it there, so it says nothing then."""
    read = _read_makefile(makefile, given)
    if read is None:
        return None
    defined, recipes, first = read
    for goal in list(dict.fromkeys(goals))[:MAX_GOALS_READ] or [first]:  # a command can name the same goal thousands of times
        for line in recipes.get(goal, []):
            found = _MAKE_RM.search(line)
            if found and found.group(1) not in defined and found.group(1) not in _MAKE_BUILTINS and not known(found.group(1)):
                return (f"this runs `make {goal}`, whose recipe `{line.strip()[:120]}` deletes through $({found.group(1)}), which nothing in the Makefile sets, "
                        "so it expands to nothing and the delete starts at the root.")
    return None


def _read_makefile(makefile: str, given: set[str]) -> tuple[set[str], dict[str, list[str]], str] | None:
    """The variables a Makefile sets, with those `given` on the command line, each target's recipe lines, and the first target, which is
    what `make` alone runs. None when it includes another file, which can set anything."""
    defined, recipes, current, first = set(given), {}, [], ""
    for line in makefile[:MAX_MAKEFILE_BYTES].split("\n"):
        if line.startswith("\t") and current:  # outside a rule, as in a conditional before the first one, a tab starts makefile text
            for target in current:
                recipes.setdefault(target, []).append(line)
            continue
        code = line.split("#", 1)[0]
        if re.match(r"[ \t]*-?s?include[ \t]", code):
            return None
        if _MAKE_CONDITIONAL.match(code):
            continue  # its own lines leave the rule before them open, as make reads them
        targets = _read_make_line(code, defined)
        if targets is not None:
            current = targets
            first = first or next((target for target in current if not target.startswith(".")), "")
    return defined, recipes, first


def _read_make_line(code: str, defined: set[str]) -> list[str] | None:
    """The targets a line's recipe lines will belong to: a rule's, or none after an assignment or other text. None for a blank line, which
    leaves the rule before it open. Adds what the line sets to `defined`, as `VAR = value` and `target: VAR = value` do."""
    assigned = _MAKE_ASSIGNS.match(code.strip())
    if assigned or code.strip().startswith("define "):
        defined.add(assigned.group(1) if assigned else code.split()[1])
        return []
    rule = _MAKE_RULE.match(code)
    if rule:
        specific = _MAKE_ASSIGNS.match(rule.group(2).strip())
        if specific:
            defined.add(specific.group(1))
        return rule.group(1).split()
    return [] if code.strip() else None


# ---------------------------------------------------------------- restores that replace what a database holds (F299)

_PRODUCTION = re.compile(r"(?:^|[^a-z0-9])(?:prod|production|prd)(?:[^a-z0-9]|$)", re.I)
_NOT_PRODUCTION = re.compile(r"(?:^|[^a-z0-9])(?:staging|stage|stg|dev|develop|development|test|testing|qa|uat|sandbox|scratch|restore|check|verify|rehearsal|drill"
                             r"|review|preview|tmp|temp|local|demo|ci|e2e)(?:[^a-z0-9]|$)", re.I)
_SET_ASIDE = re.compile(r"(?:^|[^a-z0-9])(?:old|bak|backup|retired|prev|previous|orig|original|archived?)(?:[^a-z0-9]|$)", re.I)  # renamed out of the way, not into it
_BACKUP_FILE = re.compile(r"[/\\]|\.(?:gz|dump|sql|bak|archive|tar|zst|bz2|xz|zip|bson|json)$", re.I)


def names_production(word: str) -> bool:
    return bool(_PRODUCTION.search(word))


def _names_a_restore(name: str, args: list[str]) -> bool:
    plain = [arg for arg in args if not arg.startswith("-")]
    if name in ("npm", "pnpm", "yarn", "bun"):
        candidates = plain[1:2] if plain[:1] == ["run"] else plain[:1]
    elif name in ("make", "just", "task", "rake", "rails", "invoke"):
        candidates = [arg for arg in plain if "=" not in arg]
    elif name in RUNS_A_FILE or re.fullmatch(r"python[\d.]*", name) or name in ("tsx", "ts-node", "deno"):
        candidates = plain[:2] if plain[:1] and os.path.basename(plain[0]) == "manage.py" else plain[:1]  # Django's `manage.py dbrestore`
    else:
        candidates = [name]
    return any("restore" in os.path.basename(candidate).lower() for candidate in candidates)


# A restore of data, not of packages or a cache: what it names says database, backup, dump or snapshot, or it's handed a dump file.
_DATA_WORD = re.compile(r"(?:^|[^a-z])(?:db|dbs|dbrestore|database|databases|backups?|dumps?|snapshots?)(?:[^a-z]|$)", re.I)
_DUMP_FILE = re.compile(r"\.(?:dump|sql|bak|archive|bson|backup|pgdump|dmp)(?:\.(?:gz|zst|bz2|xz|lz4))?$", re.I)
# What a restore script itself runs, when the command naming it says nothing more.
_DATA_RESTORE_CODE = re.compile(r"pg_restore|mongorestore|\bpsql\b|\bmysql\b|\bmariadb\b|sqlcmd|redis-cli|database|backup|\bdump|snapshot|\bdb\b", re.I)


def restores_data(args: list[str], name: str = "", script: str = "") -> bool:
    """Does this restore put data back, rather than packages or a cache? `script` is the text of the restore script the step runs, if any."""
    return any(_DATA_WORD.search(word) or _DUMP_FILE.search(word) for word in [name, *args]) or bool(_DATA_RESTORE_CODE.search(script or name))


_URI = re.compile(r"^(?:--?[\w-]+=)?[a-z][\w+.-]*://([^/?#\s]*)", re.I)


def production_target(args: list[str]) -> bool:
    """An argument naming production as where this acts, not a backup file whose name says where it came from. An address, as
    `mongodb://db.prod.internal/shop`, is read by its host: its path names a database or a file."""
    for arg in args:
        address = _URI.match(arg)
        if names_production(address.group(1)) if address else not _BACKUP_FILE.search(arg) and names_production(arg):
            return True
    return False


def restore_reason(name: str, args: list[str], production: bool, script: str = "") -> str | None:
    """Why a restore needs a person: it replaces what the target holds, and the target is, or may be, production. `production` says whether this
    step's arguments, settings or sourced files name production, and `script` is the text of the restore script it runs, if any. The cloud
    CLIs name their own target, so they're read alone."""
    if name in _CLOUD_RESTORES:
        return _CLOUD_RESTORES[name](args, [arg.lower() for arg in args])
    if not production or not _names_a_restore(name, args) or not restores_data(args, name, script):
        return None
    return "this restores a backup into production, over what's there, before that backup has been restored and checked somewhere safe."


def _may_be_production(target: str) -> bool:
    """Unnamed, named production, or named nothing that says it's somewhere else."""
    return not target or names_production(target) or not _NOT_PRODUCTION.search(target)


def _heroku_restore(args: list[str], lowered: list[str]) -> str | None:
    if lowered[:1] != ["pg:backups:restore"] and lowered[:2] != ["pg:backups", "restore"]:
        return None
    app = option_value(args, ("-a", "--app", "-r", "--remote"))
    return f"this restores a backup over the database of {app or 'the app this folder points at'}, replacing everything in it." if _may_be_production(app) else None


def _cloud_sql_restore(args: list[str], lowered: list[str]) -> str | None:
    if lowered[:3] != ["sql", "backups", "restore"]:
        return None
    instance = option_value(args, ("--restore-instance",))
    return f"this restores a backup over the Cloud SQL instance {instance or 'it names'}, replacing everything in it." if _may_be_production(instance) else None


def _database_renamed_into_production(args: list[str], lowered: list[str]) -> str | None:
    if "rds" not in lowered or not {"modify-db-instance", "modify-db-cluster"} & set(lowered):
        return None
    renamed = option_value(args, ("--new-db-instance-identifier", "--new-db-cluster-identifier"))
    if renamed and names_production(renamed) and not _SET_ASIDE.search(renamed):
        return f"this renames a database to {renamed}, so production's endpoint serves whatever it holds, and nothing here has queried it or run the migrations against it."
    return None


_CLOUD_RESTORES = {"heroku": _heroku_restore, "gcloud": _cloud_sql_restore, "aws": _database_renamed_into_production, "az": lambda args, lowered: None}
