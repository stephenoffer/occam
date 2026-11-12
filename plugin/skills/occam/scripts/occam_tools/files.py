"""Finding the project, its files, its git state and where tools may keep state."""

from __future__ import annotations

import fnmatch
import functools
import hashlib
import json
import os
import re
import shutil
import signal
import stat as stat_module
import subprocess
import sys
import tempfile
import threading
import time
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


# On macOS /usr/bin/git is an xcrun shim, which fails inside a sandbox such as Claude Code's, while the developer tools' own git works.
_SHIMS = {"/usr/bin/git"} if sys.platform == "darwin" else set()
_OTHER_GITS = ("/Library/Developer/CommandLineTools/usr/bin/git", "/Applications/Xcode.app/Contents/Developer/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git")


def _answers(git: str) -> bool:
    try:
        return subprocess.run([git, "--version"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _behind_the_shim() -> str | None:
    """The git the shim would run, from where xcode-select records the developer folder. The shim looks that up on every call:
    84 ms a call on this Mac, against 22 for the same git run directly, and `gate` makes about 80 calls."""
    folder = os.environ.get("DEVELOPER_DIR") or (os.path.realpath(_SELECTED_DEVELOPER_FOLDER) if os.path.islink(_SELECTED_DEVELOPER_FOLDER) else "")
    git = os.path.join(folder, "usr", "bin", "git") if folder else ""
    return git if git and os.access(git, os.X_OK) else None


_SELECTED_DEVELOPER_FOLDER = "/var/db/xcode_select_link"


@functools.lru_cache(maxsize=8)
def _usable(found: str) -> str:
    """Asked once per binary: a shim gives way to the git it would run, then is used if it answers, and otherwise to the first of the usual others that does."""
    if found not in _SHIMS:
        return found
    behind = _behind_the_shim()
    if behind and _answers(behind):
        return behind
    if _answers(found):
        return found
    return next((other for other in _OTHER_GITS if os.access(other, os.X_OK) and _answers(other)), found)


def _git_binary() -> str | None:
    """The git on PATH, looked up each time so a changed PATH or directory counts, unless it's the macOS shim and doesn't answer."""
    found = shutil.which("git")
    return _usable(found) if found else None


def _git_reads_config_environment(git: str, timeout: int) -> bool:
    """GIT_CONFIG_COUNT arrived in git 2.31. An older git ignores it, and whatever a repository names would run."""
    done = subprocess.run([git, "--version"], capture_output=True, text=True, errors="replace", timeout=min(timeout, 10))
    version = re.search(r"(\d+)\.(\d+)", done.stdout)
    return bool(version) and (int(version.group(1)), int(version.group(2))) >= (2, 31)


def can_diff_merges_by_first_parent() -> bool:
    """--diff-merges arrived in the same release."""
    git = _git_binary()
    return bool(git) and _git_reads_config_environment(git, 10)


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
    git = _git_binary()
    drivers = _driver_environment(git, root, timeout) if git else None
    if drivers is None:
        return None
    # A repository's submodule.<name>.ignore outranks -c diff.ignoreSubmodules, and asking a submodule runs what its own config names.
    command = [args[0], "--ignore-submodules=dirty", *args[1:]] if args[0] in ("status", "diff") else args
    # Left on, a plain `git diff` refreshes the index and so writes to .git, even with optional locks off.
    command = ["-c", "diff.autoRefreshIndex=false", *command] if args[0] == "diff" else command
    return [git, *_GIT_SAFETY, *command], {**os.environ, **_GIT_ENVIRONMENT, **drivers}


_running: set[subprocess.Popen] = set()


def run_git(root, *args, timeout: int = 30) -> str | None:
    """Output of a git command in `root`, or None if git is missing, it fails, or what the repository names can't be switched off."""
    invocation = _git_invocation(root, args, timeout)
    if invocation is None:
        return None
    try:
        process = subprocess.Popen(invocation[0], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=invocation[1])
    except OSError:
        return None
    _running.add(process)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return None
    except BaseException:  # interrupted, and git mustn't outlive that
        process.kill()
        process.wait()
        raise
    finally:
        _running.discard(process)
    # Decoded here and not by text mode, which turns a bare carriage return into a line break, and a diff's line counts then land on the wrong lines.
    return output.decode("utf-8", "replace") if process.returncode == 0 else None


def stop_running_git() -> None:
    """For a process about to end: a git blocked on a FIFO a repository named would otherwise outlive it."""
    for process in list(_running):
        try:
            process.kill()
        except OSError:
            pass


def stream_git(root, *args, timeout: int = 300, ok_codes: tuple = (0,), environment: dict | None = None) -> Iterator[str]:
    """Lines of a git command as they arrive, so a huge result needn't fit in memory. Raises GitProblem rather than end early and look complete."""
    invocation = _git_invocation(root, args, timeout)
    name = next(arg for index, arg in enumerate(args) if not arg.startswith("-") and (index == 0 or args[index - 1] != "-c"))
    if invocation is None:
        raise GitProblem(f"git {name} can't be run safely here")
    try:
        process = subprocess.Popen(invocation[0], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={**invocation[1], **(environment or {})})
    except OSError as error:
        raise GitProblem(f"git {name} failed to start ({error})") from error
    _running.add(process)
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
        _running.discard(process)
    if code not in ok_codes:
        raise GitProblem(f"git {name} failed or timed out here (exit {code})")


def _required_git(root, *args, timeout: int = 120) -> str:
    output = run_git(root, *args, timeout=timeout)
    if output is None:
        raise GitProblem(f"git {args[0]} failed here, so changes can't be determined")
    return output


def _holds_this_git_dir(found: Path, git_dir: Path) -> bool:
    """A repository nested in another could name that one as its files, and both hold a .git, so it has to be this one.

    A .git file names its git dir. A linked worktree's and a submodule's name it back, which one planted to borrow another repository's can't arrange.
    `git init --separate-git-dir` leaves no way back, so that can only be told from a borrowed repository by the borrowed git dir being another repository's own .git.
    """
    marker = found / ".git"
    if marker.is_dir():  # a link to someone's .git would read as this, and only a linked worktree's git dir has a commondir
        return os.path.samefile(marker, git_dir) and not (git_dir / "commondir").exists() and not (marker.is_symlink() and git_dir.resolve().name == ".git" and git_dir.resolve().parent != found.resolve())
    named = marker.read_text(errors="replace").strip()
    if marker.is_symlink() or not named.startswith("gitdir:") or not os.path.samefile(found / named[len("gitdir:"):].strip(), git_dir):
        return False
    if (git_dir / "commondir").exists():  # only a linked worktree's git dir has one, and it sits in that repository's worktrees folder
        common = git_dir / (git_dir / "commondir").read_text(errors="replace").strip()
        holder = git_dir.resolve().parent
        if holder.name != "worktrees" or not os.path.samefile(holder.parent, common):
            return False
    if (git_dir / "gitdir").is_file():  # a worktree moved by hand leaves this naming where it was, which git accepts
        named_back = git_dir / (git_dir / "gitdir").read_text(errors="replace").strip()
        return not named_back.exists() or os.path.samefile(named_back, marker)
    worktree = (run_git(git_dir, "config", "--local", "core.worktree") or "").strip()
    return os.path.samefile(git_dir / worktree, found) if worktree else git_dir.name != ".git"


def _is_own_working_tree(found: Path, path: Path) -> bool:
    """core.worktree in a repository's config can name any folder, such as a parent holding someone's home directory. A real working tree holds this repository's .git."""
    if "GIT_WORK_TREE" in os.environ:
        return True
    listed = run_git(path, "rev-parse", "--absolute-git-dir")
    try:
        if not listed or not (found / ".git").exists() or not _holds_this_git_dir(found, Path(listed.strip())):
            return False
        return ".git" in path.parts or any(os.path.samefile(found, folder) for folder in (path, *path.parents))  # samefile, since macOS accepts a path in the wrong case
    except OSError:
        return False


PROJECT_MARKERS = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", "setup.py", "pom.xml", ".git")


def root_for_path(named: str | os.PathLike) -> Path:
    """The project a path named on the command line belongs to.

    Named from inside a project, a link doesn't move the project, or following a tracked link would read files outside it with no sign it had.
    Anywhere else, the link is simply how the project was named.
    """
    path = Path(named)
    if path.is_absolute() or ".." in path.parts:
        return find_root(path)
    reached = Path(".")
    for part in path.parts:
        if (reached / part).is_symlink():
            here = Path.cwd().resolve()
            inside = run_git(here, "rev-parse", "--show-toplevel") or any((folder / marker).exists() for folder in (here, *here.parents) for marker in PROJECT_MARKERS)
            return find_root(reached if inside else path)
        reached = reached / part
    return find_root(path)


def find_root(start: str | os.PathLike = ".") -> Path:
    path = Path(start).resolve()
    if path.is_file():
        path = path.parent
    top = run_git(path, "rev-parse", "--show-toplevel")
    if top:
        found = Path(top.rstrip("\n")).resolve()
        if not _is_own_working_tree(found, path):
            raise GitProblem(f"This repository's config says its files are in {found}, which doesn't hold its .git, so reading them could expose anything")
        return found
    if (path / ".gitignore").exists():  # only here: a `.gitignore` in a home folder says nothing about the projects below it
        return path
    for candidate in (path, *path.parents):
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
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


def state_dir(root: Path, shared: bool = False) -> Path:
    """Local state, kept outside the repository so nothing dirties the tree and a repository can't plant commands or verdicts here.

    Each worktree has its own, keyed on its git folder, so a goal, baseline or golden recording in one isn't another's. `shared` is the
    repository's, keyed on the git common directory, for what worktrees coordinate on: claims. In the main checkout the two are one
    folder, as before. OCCAM_STATE_DIR is where these folders go, not a folder every repository shares.
    """
    override = os.environ.get("OCCAM_STATE_DIR")
    folder = run_git(root, "rev-parse", "--git-common-dir" if shared else "--git-dir")
    identity = (Path(root) / folder.strip()).resolve() if folder else Path(root).resolve()
    digest = hashlib.sha1(str(identity).encode()).hexdigest()[:16]
    if override and _is_writable(Path(override) / digest):
        return Path(override) / digest
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
        return parse_config(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def config_warnings(root: Path, known_rules) -> list[str]:
    """What load_config dropped from .occam.json, which would otherwise quietly mean scanning with the defaults or disabling nothing."""
    path = root / CONFIG_NAME
    if not path.is_file() or path.is_symlink():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8").lstrip("\ufeff"))
    except (OSError, ValueError) as error:
        return [f"{CONFIG_NAME} isn't valid JSON ({error}), so none of it applies."]
    if not isinstance(raw, dict):
        return [f"{CONFIG_NAME} isn't a JSON object, so none of it applies."]
    warnings = [f"{CONFIG_NAME}: \"{key}\" isn't a list of strings, so it's ignored." for key in ("ignore", "disable") if key in raw and not isinstance(raw[key], list)]
    warnings += [f"{CONFIG_NAME}: \"{key}\" holds something other than strings, which is ignored." for key in ("ignore", "disable")
                 if isinstance(raw.get(key), list) and not all(isinstance(item, str) for item in raw[key])]
    unknown_keys = sorted(set(raw) - {"ignore", "disable"})
    if unknown_keys:
        warnings.append(f"{CONFIG_NAME} has keys occam doesn't read, so they do nothing: {', '.join(unknown_keys[:5])}. It reads \"ignore\" and \"disable\".")
    unknown = [rule for rule in raw.get("disable") or [] if isinstance(rule, str) and rule not in known_rules] if isinstance(raw.get("disable"), list) else []
    if unknown:
        warnings.append(f"{CONFIG_NAME} disables rules that don't exist, so they disable nothing: {', '.join(unknown[:5])}. `occam rules` lists them.")
    return warnings


def parse_config(text: str | None) -> dict:
    """What a .occam.json text decides, so a copy from git and one from disk compare by effect, not by line endings or a byte-order mark."""
    try:
        config = json.loads((text or "").lstrip("\ufeff"))
    except ValueError:
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
    # The index still lists files deleted from disk, which aren't part of the project any more, and a folder swapped for a link would lead out of it.
    linked: dict[str, bool] = {}
    return [name for name in dict.fromkeys(listed.split("\0")) if name and _stays_inside(name) and os.path.lexists(os.path.join(root, name)) and not _through_a_link(root, name, linked)]


def _stays_inside(name: str) -> bool:
    """A hand-written index can list `../other/file`, and `git status` still reads as clean, so a name from git isn't proof it's in the project."""
    return not os.path.isabs(name) and ".." not in name.split("/")


def marked_unchanged(root: Path) -> list[str]:
    """Tracked files git has been told not to look at, so an edit to one shows up in neither status nor diff. In a sparse checkout,
    skip-worktree marks the files left out of it, which aren't there to edit, so only assume-unchanged counts."""
    listed = run_git(root, "ls-files", "-v", "-z") or ""
    sparse = (run_git(root, "config", "--bool", "core.sparseCheckout") or "").strip() == "true"
    return [entry[2:] for entry in listed.split("\0") if (entry[:2] == "S " and not sparse) or (entry[:1].islower() and entry[1:2] == " ")]


def run_bounded(command: list[str], cwd: Path, timeout: int, env: dict | None = None, input: bytes | None = None, keep: int = 8 << 20) -> subprocess.CompletedProcess:
    """Bytes in, and at the time limit everything it started stops too. `subprocess.run` kills only the direct child, so a grandchild could go on writing to the project.

    Each stream keeps at most `keep` bytes, its start and its end, around a line saying how much was cut, so endless output can't fill memory.
    It's listed in `_running` meanwhile, where a SIGTERM to occam finds its process group.
    """
    process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.PIPE if input is not None else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                               start_new_session=hasattr(os, "killpg"))
    _running.add(process)  # at once, so a SIGTERM from here on finds it
    captured: dict[str, bytes] = {}
    cut_any = [False]

    def drain(name: str, pipe) -> None:
        head, tail, total = bytearray(), bytearray(), 0
        for chunk in iter(lambda: os.read(pipe.fileno(), 1 << 16), b""):
            total += len(chunk)
            room = keep // 2 - len(head)
            head += chunk[:max(room, 0)]
            tail += chunk[max(room, 0):]
            del tail[:max(len(tail) - keep // 2, 0)]
        pipe.close()  # only this thread reads it
        cut = total - len(head) - len(tail)
        cut_any[0] = cut_any[0] or bool(cut)
        captured[name] = bytes(head) + (f"\n[occam cut {cut:,} bytes here, keeping the first and last {keep // 2:,}]\n".encode() if cut else b"") + bytes(tail)

    def feed() -> None:
        try:
            with process.stdin:
                process.stdin.write(input)
        except OSError:  # it stopped reading, which is its own business
            pass

    workers = [threading.Thread(target=drain, args=(name, getattr(process, name)), daemon=True) for name in ("stdout", "stderr")]
    workers += [threading.Thread(target=feed, daemon=True)] if input is not None else []
    finished = False
    try:
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))
        if any(worker.is_alive() for worker in workers):
            raise subprocess.TimeoutExpired(command, timeout)
        process.wait(max(0.0, deadline - time.monotonic()))
        finished = True
    finally:
        _running.discard(process)
        if hasattr(os, "killpg"):  # whatever it left running in the background goes too, finished or not, so it can't touch the next run
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
        if not finished:  # out of time or interrupted
            process.kill()
            process.wait()
            for worker in workers:
                worker.join(2)  # one that's still reading has a pipe held open by something in a session of its own, which this can't stop, so it's left behind
    done = subprocess.CompletedProcess(command, process.returncode, captured["stdout"], captured["stderr"])
    done.cut = cut_any[0]  # the middle of a stream was dropped, so it isn't the whole output
    return done


def _through_a_link(root: Path, name: str, linked: dict[str, bool]) -> bool:
    folder = name.rsplit("/", 1)[0] if "/" in name else ""
    if not folder:
        return False
    if folder not in linked:
        linked[folder] = os.path.islink(os.path.join(root, folder)) or _through_a_link(root, folder, linked)
    return linked[folder]


class OutsideProject(ValueError):
    """A named path isn't in this project. Dropping it silently would look like a clean result."""


def list_files(root: Path, targets: list[str] | None = None, config: dict | None = None, left_out: list | None = None) -> list[str]:
    """Project files to scan, relative to root. Vendored and generated files are left out unless named, since naming one is a request to read
    it, and `left_out` gets those, so a report can say how many it didn't read."""
    ignore = (config or {}).get("ignore", [])
    names = tracked_files(root)
    if names is None:
        names = _walk_files(root)
    if left_out is not None and (not targets or "." in [str(Path(target)) for target in targets]):
        left_out += [name for name in names if VENDORED.search(name)]  # folders; generated names such as lockfiles are said elsewhere
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


def empty_tree(root: Path) -> str:
    """The hash of an empty tree differs by hash algorithm, so ask rather than assume."""
    return (run_git(root, "hash-object", "-t", "tree", "/dev/null") or "").strip() or "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _diff_base(root: Path, base: str | None) -> str:
    if base:
        if run_git(root, "rev-parse", "--verify", "-q", f"{base}^{{commit}}") is None:
            if base == empty_tree(root):  # a goal started before the first commit: everything since counts
                return base
            raise BadRevision(f"No such revision: {base}")
        # What this branch did, not what the base has done since it forked. Without a common ancestor, the tip is all there is.
        return (run_git(root, "merge-base", base, "HEAD") or base).strip()
    # A repository with no commits yet compares with nothing, so staged work still shows.
    return "HEAD" if run_git(root, "rev-parse", "--verify", "-q", "HEAD") is not None else empty_tree(root)


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
    """Files whose staged version isn't what's on disk, so a scan of the working tree wouldn't see what a commit would contain.

    By comparing contents, since `git diff` believes --assume-unchanged and skip-worktree, and with the index no longer being refreshed it would also list a file whose time changed.
    """
    staged = [name for name in (run_git(root, "diff", "--cached", "--name-only", "-z", "--ignore-submodules=dirty") or "").split("\0") if name]
    if not staged:
        return []
    entries = {}
    for entry in (run_git(root, "ls-files", "--stage", "-z") or "").split("\0"):
        if "\t" in entry:
            details, name = entry.split("\t", 1)
            entries[name] = details.split()
    # A submodule is never entered, so git says whether its pointer moved, and that reads no config of its own with dirty ignored.
    moved_pointers = set((run_git(root, "diff", "--name-only", "-z") or "").split("\0")) if any(entries.get(name, ("",))[0] == "160000" for name in staged) else set()
    return [name for name in staged if name in entries and (name in moved_pointers if entries[name][0] == "160000" else not _disk_matches_blob(Path(root) / name, entries[name][0], entries[name][1]))]


def _disk_matches_blob(path: Path, mode: str, blob: str) -> bool:
    """Whether a file holds what the index does. A line ending a checkout changed isn't a difference."""
    digest = hashlib.sha256 if len(blob) == 64 else hashlib.sha1
    try:
        if os.path.islink(path) != (mode == "120000") or (mode != "120000" and not path.is_file()):  # a FIFO would never finish being read
            return False
        content = os.fsencode(os.readlink(path)) if mode == "120000" else path.read_bytes()
    except OSError:
        return False
    versions = [content, content.replace(b"\r\n", b"\n")]
    return any(digest(b"blob %d\0" % len(version) + version).hexdigest() == blob for version in versions)


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
    text = run_git(root, "show", f"{revision}:./{path}")
    return text.replace("\r\n", "\n").replace("\r", "\n") if text is not None else None  # as read from disk, so a finding's identity doesn't depend on where it was read


def in_git(root: Path) -> bool:
    return run_git(root, "rev-parse", "--git-dir") is not None


def dirty_paths(root: Path, timeout: int = 120) -> dict[str, str]:
    """Paths with uncommitted changes, and their status code. Empty outside git. Raises GitProblem if git can't say, since 'nothing is dirty' would be a lie."""
    if not in_git(root):
        if (Path(root) / ".git").exists():
            raise GitProblem("git can't read the repository here")
        return {}
    text = _required_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=dirty", timeout=timeout)
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


def churn(root: Path, commits: int = 3000, timeout: int = 120) -> dict[str, int]:
    """Commits touching each file over recent history, a good predictor of where defects concentrate."""
    text = run_git(root, "log", f"-n{commits}", "--no-merges", "--name-only", "--format=", timeout=timeout)
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


def read_text(path: Path, limit: int = MAX_FILE_BYTES) -> str | None:
    if not is_plain_file(path):
        return None
    try:
        if path.stat().st_size > limit:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", "replace").lstrip("\ufeff")
