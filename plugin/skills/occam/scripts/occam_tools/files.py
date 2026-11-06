"""Finding the project, its files, its git state and where tools may keep state."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat as stat_module
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", ".env", ".tox", ".nox", ".mypy_cache", ".ruff_cache",
             ".pytest_cache", "dist", "build", "target", "vendor", "third_party", "third-party", "bower_components", ".next", ".nuxt", ".cache",
             "site-packages", ".idea", ".vscode", "coverage", "htmlcov", ".terraform", ".gradle", "out", ".eggs", "eggs", ".ipynb_checkpoints"}
VENDORED = re.compile(r"(^|/)(node_modules|vendor|third_party|third-party|bower_components|site-packages|\.venv|venv|dist|build|target)/")
GENERATED_NAMES = re.compile(r"(\.min\.(js|css)$|\.bundle\.js$|_pb2(_grpc)?\.py$|\.pb\.go$|\.pb\.(cc|h)$|_generated\.\w+$|\.gen\.\w+$|\.g\.dart$|package-lock\.json$|yarn\.lock$|pnpm-lock\.yaml$|Cargo\.lock$|poetry\.lock$|uv\.lock$|go\.sum$)")
MAX_FILE_BYTES = 1_500_000
CONFIG_NAME = ".occam.json"


# A repository delivered with its .git folder can name programs for git to run. These switch off every route we know.
_GIT_SAFETY = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.sshCommand=false", "-c", "diff.external=", "-c", "log.showSignature=false",
               "-c", "gpg.program=false", "-c", "core.pager=cat", "-c", "core.quotePath=false", "-c", "diff.mnemonicPrefix=false", "-c", "diff.noprefix=false",
               "-c", "status.showUntrackedFiles=all", "-c", "protocol.allow=never", "-c", "diff.ignoreSubmodules=dirty", "-c", "submodule.recurse=false",
               "-c", "status.submoduleSummary=false", "-c", "diff.submodule=short", "--no-pager"]
# -c protocol.allow loses to a repository's own protocol.<name>.allow, and GIT_NO_LAZY_FETCH does nothing on git 2.39. GIT_ALLOW_PROTOCOL outranks both.
# It lists what to allow. No URL can use `_` and no alias can answer to it, where `none` would allow an alias.remote-none.
_GIT_ENVIRONMENT = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "_"}
_DRIVER_KEY = re.compile(r"^(filter|diff|merge)\.(.*)\.(clean|smudge|process|command|textconv|driver|required)$", re.I | re.S)
_driver_overrides: dict[str, dict[str, str] | None] = {}


class GitProblem(ValueError):
    """Git failed on something we rely on. Treating that as "no changes" would be a false all-clear."""


class BadRevision(GitProblem):
    """The revision to compare against doesn't exist."""


def _git_reads_config_environment(git: str, timeout: int) -> bool:
    """GIT_CONFIG_COUNT arrived in git 2.31. An older git ignores it, and whatever a repository names would run."""
    done = subprocess.run([git, "--version"], capture_output=True, text=True, errors="replace", timeout=min(timeout, 10))
    version = re.search(r"(\d+)\.(\d+)", done.stdout)
    return bool(version) and (int(version.group(1)), int(version.group(2))) >= (2, 31)


def _driver_environment(git: str, root, timeout: int) -> dict[str, str] | None:
    """Filter and diff drivers are named freely, even empty, not UTF-8 or with = in the name, so blank each one through the environment.

    Reading config runs nothing. None if it can't be read, because the drivers would then stay on.
    """
    key = str(root)
    if key not in _driver_overrides:
        overrides = None
        try:
            # GIT_CONFIG would point only this listing at one file, while the real command still reads the repository's.
            listing = {name: value for name, value in os.environ.items() if name != "GIT_CONFIG"}
            listed = subprocess.run([git, *_GIT_SAFETY, "config", "--list", "--name-only", "--null"], cwd=key, capture_output=True, timeout=min(timeout, 10), env=listing)
            if listed.returncode == 0:
                drivers = [match for match in map(_DRIVER_KEY.match, map(os.fsdecode, listed.stdout.split(b"\0"))) if match]
                if not drivers or _git_reads_config_environment(git, timeout):
                    inherited = int(os.environ.get("GIT_CONFIG_COUNT") or 0)  # settings already passed this way have to keep working
                    overrides = {"GIT_CONFIG_COUNT": str(inherited + len(drivers))}
                    for index, match in enumerate(drivers, inherited):
                        overrides[f"GIT_CONFIG_KEY_{index}"] = match.group(0)
                        overrides[f"GIT_CONFIG_VALUE_{index}"] = "false" if match.group(3).lower() == "required" else ""
        except (OSError, subprocess.TimeoutExpired):
            pass
        _driver_overrides[key] = overrides
    return _driver_overrides[key]


def _git_invocation(root, args: tuple, timeout: int) -> tuple[list[str], dict[str, str]] | None:
    """The command line and environment that keep a repository from running anything, or None if git is missing or that can't be done."""
    git = shutil.which("git")
    drivers = _driver_environment(git, root, timeout) if git else None
    if drivers is None:
        return None
    # A repository's submodule.<name>.ignore outranks -c diff.ignoreSubmodules, and asking a submodule runs what its own config names.
    command = [args[0], "--ignore-submodules=dirty", *args[1:]] if args[0] in ("status", "diff") else args
    # Left on, a plain `git diff` refreshes the index and so writes to .git, even with optional locks off.
    command = ["-c", "diff.autoRefreshIndex=false", *command] if args[0] == "diff" else command
    return [git, *_GIT_SAFETY, *command], {**os.environ, **_GIT_ENVIRONMENT, **drivers}


def run_git(root, *args, timeout: int = 30) -> str | None:
    """Output of a git command in `root`, or None if git is missing, it fails, or what the repository names can't be switched off."""
    invocation = _git_invocation(root, args, timeout)
    if invocation is None:
        return None
    try:
        done = subprocess.run(invocation[0], cwd=str(root), capture_output=True, text=True, errors="replace", timeout=timeout, env=invocation[1])
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def stream_git(root, *args, timeout: int = 300, ok_codes: tuple = (0,)) -> Iterator[str]:
    """Lines of a git command as they arrive, so a huge result needn't fit in memory. Raises GitProblem rather than end early and look complete."""
    invocation = _git_invocation(root, args, timeout)
    if invocation is None:
        raise GitProblem(f"git {args[0]} can't be run safely here")
    try:
        process = subprocess.Popen(invocation[0], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=invocation[1])
    except OSError as error:
        raise GitProblem(f"git {args[0]} failed to start ({error})") from error
    watchdog = threading.Timer(timeout, process.kill)  # a loop can't check a clock while git is silent
    watchdog.start()
    finished = False
    try:
        for raw in process.stdout:
            yield raw.decode("utf-8", "replace").rstrip("\n")
        finished = True
    finally:
        watchdog.cancel()
        if not finished:
            process.kill()
        process.stdout.close()
        code = process.wait()
    if code not in ok_codes:
        raise GitProblem(f"git {args[0]} failed or timed out here (exit {code})")


def _required_git(root, *args, timeout: int = 120) -> str:
    output = run_git(root, *args, timeout=timeout)
    if output is None:
        raise GitProblem(f"git {args[0]} failed here, so changes can't be determined")
    return output


def find_root(start: str | os.PathLike = ".") -> Path:
    path = Path(start).resolve()
    if path.is_file():
        path = path.parent
    top = run_git(path, "rev-parse", "--show-toplevel")
    if top:
        found = Path(top.strip()).resolve()
        if found != path and found not in path.parents and "GIT_WORK_TREE" not in os.environ:
            raise GitProblem(f"This repository's config says its files are in {found}, outside where it is, so reading them could expose anything")
        return found
    for candidate in (path, *path.parents):
        if any((candidate / marker).exists() for marker in ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", "setup.py", "pom.xml", ".git", ".gitignore")):
            return candidate
    working = Path.cwd().resolve()
    return working if working == path or working in path.parents else path


def _is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=str(folder)):
            return True
    except OSError:
        return False


def state_dir(root: Path) -> Path:
    """Local state, kept outside the repository so nothing dirties the tree and a repository can't plant commands or verdicts here.

    Keyed on the git common directory when there is one, so worktrees of one repository share it.
    """
    override = os.environ.get("OCCAM_STATE_DIR")
    if override and _is_writable(Path(override)):
        return Path(override)
    common = run_git(root, "rev-parse", "--git-common-dir")
    identity = (Path(root) / common.strip()).resolve() if common else Path(root).resolve()
    digest = hashlib.sha1(str(identity).encode()).hexdigest()[:16]
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    candidates = [cache_home / "occam" / digest, Path(tempfile.gettempdir()) / f"occam-{getattr(os, 'getuid', lambda: 'user')()}" / digest]
    for candidate in candidates:
        if _is_writable(candidate):
            return candidate
    raise OSError("no writable location for occam state")


def load_config(root: Path) -> dict:
    """Optional .occam.json: ignore (globs) and disable (rule ids). Configuration only, never commands. Anything malformed is dropped."""
    path = root / CONFIG_NAME
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(config, dict):
        return {}
    return {key: [item for item in config[key] if isinstance(item, str)] for key in ("ignore", "disable") if isinstance(config.get(key), list)}


def _skip_path(path: str, ignore: list[str]) -> bool:
    if VENDORED.search(path) or GENERATED_NAMES.search(path):
        return True
    return any(fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("/") + "/") for pattern in ignore)


def tracked_files(root: Path) -> list[str] | None:
    listed = run_git(root, "ls-files", "-co", "--exclude-standard", "-z", timeout=120)
    if listed is None:
        return None
    # The index still lists files deleted from disk, which aren't part of the project any more.
    return [name for name in dict.fromkeys(listed.split("\0")) if name and os.path.lexists(os.path.join(root, name))]


class OutsideProject(ValueError):
    """A named path isn't in this project. Dropping it silently would look like a clean result."""


def list_files(root: Path, targets: list[str] | None = None, config: dict | None = None) -> list[str]:
    """Project files to scan, relative to root. Vendored and generated files are left out unless named, since naming one is a request to read it."""
    ignore = (config or {}).get("ignore", [])
    names = tracked_files(root)
    if names is None:
        names = _walk_files(root)
    if not targets:
        return [name for name in names if not _skip_path(name, ignore)]
    prefixes = []
    for target in targets:
        try:
            prefixes.append(str(Path(target).resolve().relative_to(root.resolve())).replace(os.sep, "/"))
        except ValueError as error:
            raise OutsideProject(f"{target} is outside this project ({root}). Nothing was checked.") from error
    if "." in prefixes:
        return [name for name in names if not _skip_path(name, ignore)]
    chosen = []
    for name in names:
        for prefix in prefixes:
            if name == prefix or (name.startswith(prefix + "/") and not _skip_path(name[len(prefix) + 1:], [])):
                chosen.append(name)
                break
    known = set(chosen)
    chosen += [prefix for prefix in prefixes if prefix not in known and (root / prefix).is_file()]  # an ignored file, named outright
    return chosen


def is_generated_output(path: str) -> bool:
    return bool(re.search(r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|\.tox)(/|$)|\.pyc$|\.DS_Store$", path))


def _gitignore_patterns(root: Path) -> list[str]:
    """Plain patterns from a top-level .gitignore, for folders that aren't git repositories."""
    text = read_text(root / ".gitignore")  # plain files only, since a FIFO here would hang and a link could point at anything
    return [line.strip().rstrip("/") for line in (text or "").split("\n") if line.strip() and not line.startswith(("#", "!"))]


def _walk_files(root: Path) -> list[str]:
    ignored = _gitignore_patterns(root)

    def is_ignored(relative: str) -> bool:
        base = relative.rsplit("/", 1)[-1]
        return any(fnmatch.fnmatch(relative, p) or fnmatch.fnmatch(base, p) or relative.startswith(p + "/") for p in ignored)

    names = []
    for folder, subfolders, files in os.walk(root):
        relative = os.path.relpath(folder, root).replace(os.sep, "/")
        prefix = "" if relative == "." else relative + "/"
        subfolders[:] = [d for d in subfolders if d not in SKIP_DIRS and not d.endswith(".egg-info") and not is_ignored(prefix + d)]
        names += [prefix + name for name in files if not is_ignored(prefix + name)]
    return names


_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_HUNK_LINES = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _empty_tree(root: Path) -> str:
    """The hash of an empty tree differs by hash algorithm, so ask rather than assume."""
    return (run_git(root, "hash-object", "-t", "tree", "/dev/null") or "").strip() or "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _diff_base(root: Path, base: str | None) -> str:
    if base:
        if run_git(root, "rev-parse", "--verify", "-q", f"{base}^{{commit}}") is None:
            raise BadRevision(f"No such revision: {base}")
        # What this branch did, not what the base has done since it forked. Without a common ancestor, the tip is all there is.
        return (run_git(root, "merge-base", base, "HEAD") or base).strip()
    # A repository with no commits yet compares with nothing, so staged work still shows.
    return "HEAD" if run_git(root, "rev-parse", "--verify", "-q", "HEAD") is not None else _empty_tree(root)


_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote(name: str) -> str:
    """Git quotes unusual paths in C style, with octal for raw bytes, which can sit beside unescaped non-ASCII."""
    name = name.rstrip("\t")
    if not (len(name) >= 2 and name[0] == name[-1] == '"'):
        return name
    raw = bytearray()
    body = name[1:-1]
    index = 0
    while index < len(body):
        character = body[index]
        if character != "\\":
            raw += character.encode("utf-8")
            index += 1
        elif body[index + 1] in _C_ESCAPES:
            raw.append(_C_ESCAPES[body[index + 1]])
            index += 2
        else:
            raw.append(int(body[index + 1:index + 4], 8))
            index += 4
    return raw.decode("utf-8", "replace")


def _parse_diff(text: str) -> dict[str, set[int]]:
    """Changed lines per file. Hunk bodies are skipped by count, because an added line can itself look like a file header."""
    changed: dict[str, set[int]] = {}
    current = None
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith("+++ "):
            current = None if line[4:].rstrip("\t") == "/dev/null" else _unquote(line[4:])[2:]
            if current is not None:
                changed.setdefault(current, set())
        elif line.startswith("@@"):
            match = _HUNK.match(line)
            if match:
                removed, start, added = int(match.group(1) or 1), int(match.group(2)), int(match.group(3) or 1)
                if current:
                    changed[current].update(range(start, start + added))
                index += removed + added
    return changed


def fork_point(root: Path, base: str | None) -> str | None:
    """The commit a change on this branch should be compared with."""
    return _diff_base(root, base) if base else None


def _hunk_body(lines: list[str], index: int, removed: int, added: int) -> tuple[list[str], list[str], int]:
    """Walk one hunk by count, since its text can look like anything. "\\ No newline at end of file" lines aren't content."""
    gone: list[str] = []
    new: list[str] = []
    while index < len(lines) and (len(gone) < removed or len(new) < added):
        line = lines[index]
        index += 1
        if line.startswith("-") and len(gone) < removed:
            gone.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
    return gone, new, index


def diff_hunks(root: Path, base: str | None = None) -> list[tuple[str, str, int, int, list[str], list[str]]] | None:
    """(path, path before, first old line, first new line, lines removed, lines added) for each hunk. A deleted file keeps its old path. None if the diff can't be read."""
    if run_git(root, "rev-parse", "--git-dir") is None:
        return None
    try:
        text = run_git(root, "diff", "--unified=0", "--inter-hunk-context=0", "--no-color", "--no-ext-diff", "--no-textconv", "--text", "--find-renames", "--ignore-submodules=dirty",
                       "--src-prefix=a/", "--dst-prefix=b/", _diff_base(root, base), "--", timeout=120)
    except GitProblem:
        return None
    if text is None:
        return None
    hunks = []
    old = current = None
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith("--- "):
            old = None if line[4:].rstrip("\t") == "/dev/null" else _unquote(line[4:])[2:]
        elif line.startswith("+++ "):
            current = old if line[4:].rstrip("\t") == "/dev/null" else _unquote(line[4:])[2:]
        elif line.startswith("@@"):
            match = _HUNK_LINES.match(line)
            if match and current:
                gone, new, index = _hunk_body(lines, index, int(match.group(2) or 1), int(match.group(4) or 1))
                hunks.append((current, old or current, int(match.group(1)), int(match.group(3)), gone, new))
    return hunks


def changed_lines(root: Path, base: str | None = None) -> dict[str, set[int]] | None:
    """Changed line numbers per file against base (or the index plus working tree against HEAD). None without git.

    An untracked file counts as all changed, which an empty set marks. Raises GitProblem rather than report no changes when git fails.
    """
    if run_git(root, "rev-parse", "--git-dir") is None:
        return None
    changed = _parse_diff(_required_git(root, "diff", "--unified=0", "--inter-hunk-context=0", "--no-color", "--no-ext-diff", "--no-textconv", "--text", "--find-renames", "--ignore-submodules=dirty",
                                        "--src-prefix=a/", "--dst-prefix=b/", _diff_base(root, base), "--"))
    for name in _required_git(root, "ls-files", "-o", "--exclude-standard", "-z").split("\0"):
        if name:
            changed[name] = set()
    for new_path in removed_and_renamed(root, base)[1]:  # a pure rename has no hunks, so the diff above doesn't show it
        changed.setdefault(new_path, set())
    return changed


def submodule_paths(root: Path) -> list[str]:
    """Submodules, which are never entered: their config could name programs, and only the pointer is reported as changed."""
    listed = run_git(root, "ls-files", "--stage", "-z") or ""
    return [entry.split("\t", 1)[1] for entry in listed.split("\0") if entry.startswith("160000 ") and "\t" in entry]


def staged_differently(root: Path) -> list[str]:
    """Files whose staged version isn't what's on disk, so a scan of the working tree wouldn't see what a commit would contain."""
    listed = run_git(root, "diff", "--name-only", "-z", "--ignore-submodules=dirty") or ""
    staged = set((run_git(root, "diff", "--cached", "--name-only", "-z", "--ignore-submodules=dirty") or "").split("\0"))
    return [name for name in listed.split("\0") if name and name in staged]


def removed_and_renamed(root: Path, base: str | None = None) -> tuple[list[str], dict[str, str]]:
    """Paths this change deleted, and new path to old path for what it renamed."""
    listed = _required_git(root, "diff", "--name-status", "-z", "--find-renames", "--ignore-submodules=dirty", _diff_base(root, base), "--")
    parts = listed.split("\0")
    deleted: list[str] = []
    renamed: dict[str, str] = {}
    index = 0
    while index < len(parts) and parts[index]:
        status = parts[index]
        if status[0] in "RC":
            renamed[parts[index + 2]] = parts[index + 1]
            index += 3
        else:
            if status[0] == "D":
                deleted.append(parts[index + 1])
            index += 2
    return deleted, renamed


def file_at(root: Path, revision: str, path: str) -> str | None:
    return run_git(root, "show", f"{revision}:./{path}")


def in_git(root: Path) -> bool:
    return run_git(root, "rev-parse", "--git-dir") is not None


def dirty_paths(root: Path) -> dict[str, str]:
    """Paths with uncommitted changes, and their status code. Empty outside git. Raises GitProblem if git can't say, since 'nothing is dirty' would be a lie."""
    if not in_git(root):
        return {}
    text = _required_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=dirty")
    dirty = {}
    entries = text.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, name = entry[:2], entry[3:]
        dirty[name] = status
        if status[0] in "RC":
            index += 1
    return dirty


def churn(root: Path, commits: int = 3000) -> dict[str, int]:
    """Commits touching each file over recent history, a good predictor of where defects concentrate."""
    text = run_git(root, "log", f"-n{commits}", "--no-merges", "--name-only", "--format=", timeout=120)
    counts: dict[str, int] = {}
    for line in (text or "").split("\n"):
        if line:
            counts[line] = counts.get(line, 0) + 1
    return counts


def is_plain_file(path: Path) -> bool:
    """A regular file, not reached through a symlink. A symlink could point anywhere, and reading a FIFO would hang forever."""
    try:
        return not path.is_symlink() and stat_module.S_ISREG(path.stat().st_mode)
    except OSError:
        return False


def read_text(path: Path) -> str | None:
    if not is_plain_file(path):
        return None
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", "replace").lstrip("\ufeff")
