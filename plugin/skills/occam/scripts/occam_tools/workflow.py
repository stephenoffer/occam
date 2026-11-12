"""Working toward a goal, next to other agents: an advisory claim table, and a ledger of what done means."""

from __future__ import annotations

import contextlib
import fnmatch
import json
import hashlib
import os
import re
import shlex
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from . import files as filesystem, manifests, query_code
from .source import language_of
from .zero_tests import ran_no_tests

# Limits `goal constrain --no` can check itself, beside a path that mustn't change.
LIMITS = {"new-dependency": "No new dependencies", "new-file": "No new files", "api-break": "Keep the public API compatible"}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS baseline (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS claims (path TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@contextlib.contextmanager
def database(root: Path, shared: bool = False) -> Iterator[sqlite3.Connection]:
    """Shared by every command and agent on this machine for this worktree, or with `shared` for the whole repository. Explicit transactions,
    with a long wait for the lock. Closed on leaving, with a transaction left open by a failure rolled back."""
    connection = sqlite3.connect(str(filesystem.state_dir(root, shared) / "occam.db"), timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.executescript(_SCHEMA)
        yield connection
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


# ---------------------------------------------------------------- coordination


def active_claims(root: Path) -> dict[str, str]:
    try:
        with database(root, shared=True) as db:
            now = time.time()
            db.execute("DELETE FROM claims WHERE expires <= ?", (now,))
            return {path: owner for path, owner in db.execute("SELECT path, owner FROM claims")}
    except (OSError, sqlite3.Error):  # claims are advisory, so failing to read them can't stop work
        return {}


def _covers(parent: str, child: str) -> bool:
    return parent == "." or child == parent or child.startswith(parent.rstrip("/") + "/")


def claim_holder(claims: dict[str, str], path: str) -> str | None:
    """Who holds this path, directly or through a folder they claimed."""
    return next((owner for held, owner in claims.items() if _covers(held, path)), None)


def coord(root: Path, action: str, paths: list[str], owner: str | None, ttl: int) -> tuple[str, int]:
    relative = [_relative(root, path) for path in paths]
    if action in ("claim", "release") and not owner:
        return "Name yourself with --owner, so two agents can't both hold a claim under a shared default.", 2
    if action == "claim":
        return _claim(root, relative, owner, ttl)
    if action == "release":
        with database(root, shared=True) as db:
            if relative:
                db.executemany("DELETE FROM claims WHERE path = ? AND owner = ?", [(path, owner) for path in relative])
            else:
                db.execute("DELETE FROM claims WHERE owner = ?", (owner,))
        return f"Released {len(relative) or 'all'} claims for {owner}.", 0
    if action == "check":
        return _check(root, relative, owner)
    return _status(root), 0


def _relative(root: Path, path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return path


def _claim(root: Path, paths: list[str], owner: str, ttl: int) -> tuple[str, int]:
    if not paths:
        return "Name the paths to claim.", 2
    now = time.time()
    with database(root, shared=True) as db:
        db.execute("BEGIN IMMEDIATE")
        held = {path: who for path, who, expires in db.execute("SELECT path, owner, expires FROM claims") if expires > now and who != owner}
        conflict = [f"{path} (held by {claim_holder(held, path)})" for path in paths if claim_holder(held, path)]
        conflict += [f"{path} (held by {who})" for path, who in held.items() if any(_covers(mine, path) for mine in paths)]
        if conflict:
            db.execute("ROLLBACK")
            return "Not claimed: " + ", ".join(conflict) + ". Pick other work, or ask them.", 1
        db.executemany("INSERT OR REPLACE INTO claims VALUES (?, ?, ?)", [(path, owner, now + ttl) for path in paths])
        db.execute("COMMIT")
    return f"{owner} holds {len(paths)} paths for {ttl}s. Claims are advisory: they coordinate cooperating agents, and they don't lock anything.", 0


def _check(root: Path, paths: list[str], owner: str | None) -> tuple[str, int]:
    claims = active_claims(root)
    dirty = filesystem.dirty_paths(root)
    problems = []
    for path in paths:
        holders = {who for held, who in claims.items() if (_covers(held, path) or _covers(path, held)) and who != owner}
        problems += [f"{path} is claimed by {who}" for who in sorted(holders)]
        changed = [name for name in dirty if _covers(path, name)]
        if changed:
            problems.append(f"{path} has uncommitted changes in {', '.join(changed[:5])}. Read the diff first, because they may not be yours")
    if problems:
        return "\n".join(problems), 1
    return "Clear.", 0


def _status(root: Path) -> str:
    lines = []
    try:
        dirty = filesystem.dirty_paths(root)
    except filesystem.GitProblem as error:  # the question here is who else is working, and the rest of this can still say something
        dirty = {}
        lines.append(f"{error}, so uncommitted work is unknown. Assume there's some.")
    worktrees = (filesystem.run_git(root, "worktree", "list") or "").strip().split("\n")
    if len(worktrees) > 1:
        lines += [f"{len(worktrees)} worktrees:", *[f"  {line}" for line in worktrees[:10]]]
    if filesystem.run_git(root, "rev-parse", "--git-dir") is None:
        lines.append("Not a git repository, so there's no record of other changes. Be careful with whole-file writes, and check modification times:")
        recent = _recently_modified(root)
        lines += [f"  {path}  {age}s ago" for path, age in recent] or ["  nothing changed in the last 30 minutes."]
    if dirty:
        lines.append(f"{len(dirty)} uncommitted files. Assume they're someone's work:")
        lines += [f"  {status} {path}" for path, status in sorted(dirty.items())[:25]]
    log = (filesystem.run_git(root, "log", "--since=2.hours", "--format=%h %an: %s", "-n", "10") or "").strip()
    if log:
        lines += ["Recent commits:", *[f"  {line}" for line in log.split("\n")]]
    submodules = filesystem.submodule_paths(root)
    if submodules:
        lines.append("Submodules aren't looked inside, so changes there don't show: " + ", ".join(submodules[:8]))
    if (root / ".git" / "index.lock").exists():
        lines.append("git's index is locked, so something is committing now.")
    claims = active_claims(root)
    if claims:
        lines += ["Claims:", *[f"  {path}: {owner}" for path, owner in sorted(claims.items())[:25]]]
    return "\n".join(lines) or "No sign of other work here."


def _recently_modified(root: Path, seconds: int = 1800) -> list[tuple[str, int]]:
    now = time.time()
    found = []
    for path in filesystem.list_files(root, None, filesystem.load_config(root))[:20000]:
        try:
            age = now - (root / path).stat().st_mtime
        except OSError:
            continue
        if age < seconds:
            found.append((path, int(age)))
    return sorted(found, key=lambda item: item[1])[:20]


# ---------------------------------------------------------------- goal ledger


def _load(root: Path) -> dict | None:
    with database(root) as db:
        row = db.execute("SELECT value FROM kv WHERE key = 'goal'").fetchone()
    return json.loads(row[0]) if row else None


def _save(root: Path, goal_state: dict) -> None:
    with database(root) as db:
        db.execute("INSERT OR REPLACE INTO kv VALUES ('goal', ?)", (json.dumps(goal_state),))


def _change_goal(root: Path, change) -> dict | None:
    """Read, change and write in one transaction, so agents adding requirements at once can't lose each other's."""
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM kv WHERE key = 'goal'").fetchone()
        if not row:
            db.execute("ROLLBACK")
            return None
        state = json.loads(row[0])
        change(state)
        db.execute("INSERT OR REPLACE INTO kv VALUES ('goal', ?)", (json.dumps(state),))
        db.execute("COMMIT")
    return state


def _start_goal(root: Path, text: str, **extra) -> dict | None:
    """Create the goal unless one exists, in one transaction, so two agents starting at once can't both think they did. Limits read from a
    request that nobody has added requirements to yet carry over. Returns the goal already there, if it stays."""
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM kv WHERE key = 'goal'").fetchone()
        state = json.loads(row[0]) if row else None
        kept = state["constraints"] if state is not None and state.get("from_request") and not state["requirements"] else None
        if state is not None and kept is None:
            db.execute("ROLLBACK")
            return state
        db.execute("INSERT OR REPLACE INTO kv VALUES ('goal', ?)", (json.dumps({**_new_goal(root, text), **({"constraints": kept} if kept else {}), **extra}),))
        db.execute("COMMIT")
    return None


def _tree_state(root: Path, paths: list[str] | None = None, tracked_only: bool = False) -> str:
    """A cheap identity for the working tree's contents, so old evidence can be recognized as stale. `tracked_only` leaves out what git
    doesn't track (outside git, what isn't code), which is where a check's own reports go: junit.xml, .coverage, htmlcov/."""
    digest = hashlib.sha1()
    head = filesystem.run_git(root, "rev-parse", "HEAD")
    if head is not None:
        digest.update(head.encode())
        # What a check leaves behind, __pycache__ and the like where git doesn't ignore it, isn't a change to the code it checked.
        status = [line for line in (filesystem.run_git(root, "status", "--porcelain=v1") or "").split("\n") if not filesystem.is_generated_output(line[3:].strip('"'))]
        # A new module not yet added is code all the same; a report a check writes (junit.xml, .coverage, htmlcov/) isn't.
        report = lambda name: language_of(name) in (None, "html") or bool(re.search(r"(?:^|/)(?:coverage|htmlcov|lcov-report|\.nyc_output|test-results)/", name))  # noqa: E731
        untracked = tuple(line[3:].strip('"') for line in status if line.startswith("??"))
        status = [line for line in status if not (tracked_only and line.startswith("??") and report(line[3:].strip('"')))]
        digest.update("\n".join(status).encode())
        for name in [*filesystem.dirty_paths(root), *filesystem.marked_unchanged(root)]:  # git hides an edit to the second from status
            if filesystem.is_generated_output(name) or (tracked_only and report(name) and any(name == u or (u.endswith("/") and name.startswith(u)) for u in untracked)):
                continue
            path = root / name
            try:  # a link's own text is what git tracks, and following one to a FIFO would wait forever
                digest.update(os.readlink(path).encode() if path.is_symlink() else path.read_bytes() if filesystem.is_plain_file(path) else b"")
            except OSError:
                continue
        return digest.hexdigest()[:16]
    for name in filesystem.list_files(root, paths, filesystem.load_config(root)):
        if tracked_only and not language_of(name):
            continue
        try:  # ctime too: a tool that puts the modification time back can't put that back, so a same-size edit still shows
            stat = (root / name).stat()
            digest.update(f"{name}\0{stat.st_size}\0{stat.st_mtime_ns}\0{stat.st_ctime_ns}".encode())
        except OSError:
            continue
    return digest.hexdigest()[:16]


def _new_goal(root: Path, text: str) -> dict:
    # No commit yet still has a base, the empty tree, or a later commit of a forbidden file couldn't be seen.
    head = (filesystem.run_git(root, "rev-parse", "HEAD") or "").strip() or (filesystem.empty_tree(root) if filesystem.in_git(root) else None)
    in_git = filesystem.in_git(root)
    return {"goal": text, "requirements": [], "constraints": [], "scope": [], "created": time.time(), "base": head,
            "snapshot": {} if in_git else _snapshot(root), "untracked": _untracked(root) if in_git else []}


def _add_constraint(root: Path, current: dict, constraint: dict) -> None:
    current["constraints"].append(constraint)
    if constraint.get("no") == "new-file" and "untracked" not in current and filesystem.in_git(root):
        current["untracked"] = _untracked(root)  # a goal from before this was recorded: what's untracked now counts as already there


# The three limits a goal checks itself, as a request states them: directives only. "No new dependencies, please." sets one, and so does
# "don't add any new files". "There are no new dependencies in this PR", a quoted line, or a limit with an exception doesn't.
_CLAUSE = r"(?:^|(?<=[.;:!?,(])\s*|\b(?:and|but|also|please|with|so)\s+)"
_THINGS = r"(?:new\s+|extra\s+|additional\s+|third[- ]party\s+|external\s+)*(?:dependenc(?:y|ies)|deps|packages|librar(?:y|ies))\b"
_STATED_LIMITS = {
    "new-dependency": re.compile(_CLAUSE + r"no\s+" + _THINGS + r"|\b(?:don'?t|do not|without|avoid)\s+(?:add|adding|introduc\w*|pull\w* in|install\w*)(?:\s+any)?\s+" + _THINGS
                                 + r"|\b(?:standard|std)[- ]?lib(?:rary)? only\b", re.I | re.M),
    "new-file": re.compile(_CLAUSE + r"no\s+new\s+files?\b|\b(?:don'?t|do not|without)\s+(?:add|adding|create|creating)\s+(?:any\s+)?(?:new\s+)?files?\b", re.I | re.M),
    "api-break": re.compile(r"\b(?:don'?t|do not|without)\s+(?:chang\w*|break\w*|alter\w*|modify\w*)\s+(?:the\s+|our\s+|its\s+|any\s+)?(?:public\s+|exported\s+)?(?:api|interface)s?\b"
                            r"|\b(?:keep|preserve|maintain)\s+(?:the\s+|our\s+|its\s+)?(?:public\s+|exported\s+)?(?:api|interface)s?"
                            r"(?=\s*(?:[.,;!?)]|$|as (?:it )?is\b|the same\b|unchanged\b|stable\b|intact\b|(?:backwards?[- ])?compatible\b))"
                            r"|\bno\s+(?:public\s+)?api\s+changes?\b|\b(?:public\s+)?(?:api|interface)\s+(?:must|should|can)(?:n['’]?t| not)\s+(?:change|break)", re.I | re.M),
}
_EXCEPTED = re.compile(r"\b(?:unless|except|other than|apart from|besides|beyond|if (?:you )?(?:really )?need|if needed|if necessary|where needed)\b", re.I)


def stated_limits(request: str) -> list[str]:
    text = re.sub(r"(?m)^\s*>.*$", "", request)  # a quoted line is someone else's words
    found = []
    for limit, pattern in _STATED_LIMITS.items():
        if any(not _EXCEPTED.search(re.split(r"[.!?\n]", text[match.end():], maxsplit=1)[0]) for match in pattern.finditer(text)):
            found.append(limit)
    return found


def record_stated_limits(root: Path, request: str, session: str = "") -> list[str]:
    """Record the limits the user's own request states, so `gate` and `goal verify` check them, the owner's call on 2026-11-08 (DESIGN
    `session-recall-owner-calls`). A goal started this way belongs to its session, for as long as that runs: another session's request
    replaces or clears it unless someone has added requirements to it, and a goal started by hand only gains the limits. `occam goal clear`
    lifts them. Returns what was newly recorded."""
    stated = stated_limits(request)
    state = _load(root)
    if state is not None and state.get("from_request") and state.get("session") != session and not state["requirements"]:
        _clear_goal(root)
        state = None
    if not stated:
        return []
    if state is None:
        _start_goal(root, request.strip().split("\n")[0][:200], from_request=True, session=session)  # if another got there first, its goal gains the limits
    added: list[str] = []

    def add(current: dict) -> None:
        have = {constraint.get("no") for constraint in current["constraints"]}
        for limit in (limit for limit in stated if limit not in have):
            _add_constraint(root, current, {"text": f"{LIMITS[limit]}, as the request says", "forbid": None, "no": limit})
            added.append(LIMITS[limit])

    _change_goal(root, add)
    return added


def _clear_goal(root: Path) -> None:
    with database(root) as db:
        db.execute("DELETE FROM kv WHERE key = 'goal'")


def goal(root: Path, args) -> tuple[str, int]:
    text = " ".join(args.text).strip()
    state = _load(root)
    if args.action == "init":
        if not text:
            return "State the goal: the observable outcome, not the steps.", 2
        existing = _start_goal(root, text)
        if existing is not None:  # agents share this store, so starting over silently would throw away someone's requirements
            return f"A goal is already recorded: {existing['goal']}\n`occam goal clear` first if it's really finished with.", 2
        return f"Goal set: {text}\nAdd what must be true with `occam goal add \"...\" --check \"command\"`, and limits with `occam goal constrain`.", 0
    if args.action == "clear":
        _clear_goal(root)
        return "Goal cleared.", 0
    if state is None:
        return "No goal yet. `occam goal init \"the outcome\"` starts one.", 2
    if args.action == "add":
        if not text:
            return "State the requirement as something observable.", 2
        if args.check and needs_a_shell(args.check):
            return f"Not added: that check {NEEDS_A_SHELL}", 2

        def add(current: dict) -> None:
            current["requirements"].append({"id": len(current["requirements"]) + 1, "text": text, "check": args.check, "status": "not run", "tree": None, "detail": ""})

        state = _change_goal(root, add)
        if state is None:
            return "No goal any more: it was cleared meanwhile, so nothing was added.", 2
        return f"R{len(state['requirements'])}: {text}" + ("" if args.check else "  (no check yet, so report it unverified until there is one)"), 0
    if args.action == "constrain":
        limit = getattr(args, "no", None)
        if args.forbid and limit:
            return "One constraint at a time: --forbid or --no.", 2
        if not text and not args.forbid and not limit:
            return "State the constraint.", 2
        constraint = {"text": text or LIMITS.get(limit) or f"Don't change {args.forbid}", "forbid": _project_pattern(root, args.forbid or "") or args.forbid}
        if limit:
            constraint["no"] = limit
        _change_goal(root, lambda current: _add_constraint(root, current, constraint))
        checked = "Checked" if args.forbid or limit else "Reread"
        return f"Constraint recorded: {constraint['text']}. {checked} at every `goal verify`.", 0
    if args.action == "scope":
        _change_goal(root, lambda current: current.update(scope=[_project_pattern(root, item) for item in args.text]))
        return f"In scope: {', '.join(args.text)}. Changes elsewhere are reported as drift.", 0
    if args.action == "condition":
        return _condition(state), 0
    if args.action == "verify":
        return _verify(root, state, args)
    return _render_goal(root, state), 0


def _condition(state: dict) -> str:
    command = Path(__file__).resolve().parents[1] / "occam.py"
    return (f"{state['goal']}. `python3 {command} goal verify` prints ALL VERIFIED and exits 0, and its output appears in the conversation. "
            "Stop and report if a constraint would have to be broken or a decision is needed from the user.")


def needs_a_shell(command: str) -> bool:
    """Checks run with no shell, so `cd backend && pytest` runs `cd` with the rest as arguments, and passes without testing anything."""
    quote = ""
    position = 0
    while position < len(command):
        character = command[position]
        following = command[position + 1:position + 2]
        if quote == "'":
            quote = "" if character == "'" else quote
        elif character == "\\":
            position += 1
        elif character == "`" or (character == "$" and (following in ("(", "{") or following.isalpha() or following == "_")):
            return True  # inside double quotes too: `test -n "$(pytest | grep passed)"` would test the literal text
        elif quote == '"':
            quote = "" if character == '"' else quote
        elif character in "'\"":
            quote = character
        elif character in ";&|<>()\n":
            return True
        position += 1
    return False


NEEDS_A_SHELL = "uses shell syntax, but checks run with no shell, so it wouldn't test what it says. Wrap it: sh -c '...'"


def _run_check(root: Path, command: str, timeout: int) -> tuple[bool, str]:
    if needs_a_shell(command):
        return False, NEEDS_A_SHELL
    try:
        done = filesystem.run_bounded(shlex.split(command), root, timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except (OSError, ValueError) as error:
        return False, f"couldn't run: {error}"
    stdout, stderr = done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
    output = (stdout + stderr).strip().split("\n")
    tail = " / ".join(line.strip() for line in output[-2:] if line.strip())[:200]
    if done.returncode == 0 and ran_no_tests(stdout + "\n" + stderr):
        return False, "ran zero tests"
    return done.returncode == 0, f"exit {done.returncode}: {tail}"


SNAPSHOT_FILES = 50000
_TRUNCATED = "\0truncated"


def _snapshot(root: Path) -> dict[str, str]:
    """Outside git there's no history to compare with, so a goal records what the files were when it began."""
    found = {}
    listed = filesystem.list_files(root, None, {})
    for name in listed[:SNAPSHOT_FILES]:
        if filesystem.is_plain_file(root / name):
            stat = (root / name).stat()
            found[name] = f"{stat.st_size}:{stat.st_mtime_ns}"
    if len(listed) > SNAPSHOT_FILES:
        found[_TRUNCATED] = str(len(listed))  # so what lies past the limit is reported unchecked, not unchanged
    return found


def _changed_files(root: Path, state: dict, base: str | None) -> list[str]:
    """Everything this work touched, including what it deleted and where renames came from."""
    changed = filesystem.changed_lines(root, base or state.get("base"))
    if changed is None:
        before, now = state.get("snapshot") or {}, _snapshot(root)
        return sorted(name for name in {*before, *now} if before.get(name) != now.get(name) and name != _TRUNCATED)
    deleted, renamed = filesystem.removed_and_renamed(root, base or state.get("base"))
    return sorted({*changed, *deleted, *renamed.values()})


def _verify(root: Path, state: dict, args) -> tuple[str, int]:
    lines = [f"Goal: {state['goal']}"]
    before = _tree_state(root, tracked_only=True)
    results: dict[int, dict] = {}
    for requirement in state["requirements"]:
        passed, detail = _run_check(root, requirement["check"], args.timeout) if requirement.get("check") else (False, "no check given")
        status = "verified" if passed else "failed" if requirement.get("check") else "not run"
        results[requirement["id"]] = {"status": status, "detail": detail, "tree": None, "check": requirement.get("check")}
    tree = _tree_state(root)  # the receipt is for the tree as the checks left it, their own reports included
    for result in results.values():
        result["tree"] = tree if result["check"] else None
    if _tree_state(root, tracked_only=True) != before:  # a check, or someone else, changed the code while the checks ran, so no pass is about the code there now
        for result in results.values():
            if result["status"] == "verified":
                result.update(status="stale", detail="the files changed while the checks ran, by a check or someone else, so run verify again")
    started = state.get("created")

    def record(current: dict) -> None:  # merged rather than overwritten, because checks take time and others may add requirements meanwhile
        if current.get("created") != started:
            return  # cleared and started again meanwhile: an old R1 isn't the new R1
        for requirement in current["requirements"]:
            result = results.get(requirement["id"])
            if result and result["check"] == requirement.get("check"):
                requirement.update({key: value for key, value in result.items() if key != "check"})

    state = _change_goal(root, record)
    if state is None or state.get("created") != started:
        lines.append("NOT DONE: the goal was cleared or replaced while its checks ran, so these results weren't recorded. Run verify again.")
        return "\n".join(lines), 1
    failed = 0
    for requirement in state["requirements"]:
        unverified = requirement["status"] != "verified" or requirement["id"] not in results
        failed += unverified
        lines.append(f"  R{requirement['id']} {requirement['status']:<9} {requirement['text']}" + (f"  ({requirement['detail']})" if unverified else ""))
    if not state["requirements"]:
        failed += 1
        lines.append("  No requirements recorded, so nothing is verified.")
    try:
        drift = scope_problems(root, state, args.base)
    except filesystem.GitProblem as error:
        lines.append(f"NOT DONE: {error}")
        return "\n".join(lines), 2
    lines += [f"  {problem}" for problem in drift]
    if state["constraints"]:
        lines += ["Constraints to reread against your diff:", *[f"  - {c['text']}" for c in state["constraints"]]]
    if failed or drift:
        lines.append(f"NOT DONE: {failed} requirements unverified, {len(drift)} scope problems.")
        return "\n".join(lines), 1
    lines.append("ALL VERIFIED on the current tree. This covers only the recorded checks. Read the diff against the request as well.")
    return "\n".join(lines), 0


def _project_pattern(root: Path, pattern: str) -> str:
    """`./migrations`, `src/../migrations` and an absolute path all mean `migrations`, and comparing them as text would pass a violation. `./` is from where it was typed."""
    if not pattern:
        return pattern
    if os.path.isabs(pattern) or pattern.startswith(("./", "../")):
        try:
            return str(Path(os.path.abspath(pattern)).resolve().relative_to(root.resolve())).replace(os.sep, "/")
        except ValueError:
            return pattern
    return os.path.normpath(pattern).replace(os.sep, "/")


def new_dependencies(root: Path, base: str, changed: list[str], gone: list[str] | tuple = ()) -> list[str]:
    """Packages the manifests declare now that none declared at `base`, as "name (manifest)". Every manifest is read on both sides, through
    its includes and setup helpers, so a dependency added only in `-r base.txt` or a setup.py's helper module counts, and one moved between
    manifests doesn't."""
    def at_base(name: str) -> str:
        text = filesystem.file_at(root, base, name)
        if text is None:
            raise FileNotFoundError(name)
        return text

    then = [path for path in (filesystem.run_git(root, "ls-tree", "-r", "--name-only", "-z", base) or "").split("\0") if path and manifests.DEPENDENCY_FILE.search(path)]
    listed = filesystem.run_git(root, "ls-files", "-z") or ""
    current = sorted({*(path for path in listed.split("\0") if path and manifests.DEPENDENCY_FILE.search(path)),
                      *(path for path in changed if manifests.DEPENDENCY_FILE.search(path) and (root / path).is_file())} - set(gone))
    before, now = manifests.read_manifests(root, then, at_base), manifests.read_manifests(root, current)
    return sorted(f"{name} ({now[ecosystem][name]})" for ecosystem in ("python", "node", "rust", "go") for name in now[ecosystem] if name not in before[ecosystem])


def _moved_here(root: Path, base: str, new: set[str]) -> set[str]:
    """New paths holding exactly what a deleted file held at base: a rename made with `mv`, which git sees only once both sides are staged."""
    deleted = filesystem.removed_and_renamed(root, base)[0]
    if not deleted or not new:
        return set()
    listed = filesystem.run_git(root, "ls-tree", "-z", base, "--", *deleted) or ""  # one call, `mode type blob<TAB>path` per deleted file
    gone = {entry.split("\t", 1)[0].split()[-1] for entry in listed.split("\0") if "\t" in entry}
    candidates = sorted(path for path in new if (root / path).is_file())
    hashed = (filesystem.run_git(root, "hash-object", "--", *candidates) or "").split()
    return {path for path, blob in zip(candidates, hashed) if blob in gone} if len(hashed) == len(candidates) else set()


def _untracked(root: Path) -> list[str]:
    listed = filesystem.run_git(root, "ls-files", "-o", "--exclude-standard", "-z")
    if listed is None:
        raise filesystem.GitProblem("git couldn't list untracked files")
    return sorted(name for name in listed.split("\0") if name)


_NO_API = {"shell", "sql", "html", "css", "scss", "markdown", "yaml", "json", "toml", "xml", "dockerfile", "makefile", "notebook", "terraform", "hcl", "text"}


def _broken_limit(root: Path, base: str, limit: str, changed: list[str], already_untracked: list[str]) -> tuple[list[str], list[str]]:
    """What in this change breaks one of LIMITS, compared with what the base held, and what couldn't be compared."""
    base = filesystem.fork_point(root, base)  # what this branch did, not what the base has done since, as the diff of changed files reads it
    if limit == "new-file":
        added = filesystem.run_git(root, "diff", "--name-only", "-z", "--diff-filter=A", "--find-renames", "--ignore-submodules=dirty", base, "--")
        if added is None:
            raise filesystem.GitProblem(f"git couldn't list what was added since {base}")
        # A file that was there, untracked, when the goal began isn't new, whether or not it has been added to git since.
        new = ({name for name in added.split("\0") if name} | set(_untracked(root))) - set(already_untracked)
        return sorted(new - _moved_here(root, base, new)), []
    if limit == "new-dependency":
        return new_dependencies(root, base, changed), []
    found = query_code.api(root, None, base, top=50)
    broken = [f"{row['where']} {row['name']} removed" for row in found["removed"]]
    broken += [f"{row['where']} {row['name']}: {'; '.join(row['breaking'] + row.get('defaults', []))}" for row in found["changed"] if row["breaking"] or row.get("defaults")]
    # Changed files whose API this can't read, and exports built at runtime, are open, not kept.
    unread = [*found["unread"], *(f"{count} changed {language} files, whose API isn't compared" for language, count in found.get("outside", []) if language not in _NO_API),
              *(f"{path} (its __all__ is built at runtime)" for path in found.get("computed", []))]
    return broken, unread


def _listed(hit: list[str]) -> str:
    return ", ".join(hit[:5]) + (f" and {len(hit) - 5} more" if len(hit) > 5 else "")


def _constraint_problems(root: Path, state: dict, base: str | None, changed: list[str], constraint: dict, costly: bool) -> list[str]:
    if constraint.get("no") in LIMITS:
        if (base or state.get("base")) is None:  # outside git a goal keeps only file sizes and times, so the base's contents are gone
            return [f"NOT CHECKED: {constraint['text']}: needs git, to see what the base held"]
        if constraint["no"] == "api-break" and not costly:
            return [f"NOT CHECKED here: {constraint['text']}. `occam goal verify` checks it."]
        hit, unread = _broken_limit(root, base or state["base"], constraint["no"], changed, state.get("untracked") or [])
    else:
        pattern = _project_pattern(root, constraint.get("forbid") or "")
        hit = [path for path in changed if fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("*/") + "/")] if pattern else []
        unread = []
    return [*([f"VIOLATED: {constraint['text']}: {_listed(hit)}"] if hit else []), *([f"NOT CHECKED: {constraint['text']}: couldn't compare {_listed(unread)}"] if unread else [])]


def scope_problems(root: Path, state: dict, base: str | None, costly: bool = True) -> list[str]:
    """What breaks the goal's constraints and scope. Without `costly`, the public API isn't compared, since that reads every module."""
    changed = _changed_files(root, state, base)
    problems = [problem for constraint in state["constraints"] for problem in _constraint_problems(root, state, base, changed, constraint, costly)]
    beyond = (state.get("snapshot") or {}).get(_TRUNCATED)
    if beyond and (state["constraints"] or state["scope"]):
        problems.append(f"NOT CHECKED: outside git only the first {SNAPSHOT_FILES:,} of {int(beyond):,} files are compared, so a change past them can't be seen.")
    if state["scope"]:
        scope = [_project_pattern(root, s) for s in state["scope"]]
        outside = [path for path in changed if not any(fnmatch.fnmatch(path, s) or path == s or path.startswith(s.rstrip("/") + "/") for s in scope)]
        if outside:
            problems.append(f"DRIFT: changed outside the stated scope: {', '.join(outside[:8])}. Explain it or ask.")
    return problems


def _render_goal(root: Path, state: dict) -> str:
    tree = _tree_state(root)
    lines = [f"Goal: {state['goal']}"]
    for requirement in state["requirements"]:
        status = requirement["status"]
        if status == "verified" and requirement.get("tree") != tree:
            status = "stale"
        lines.append(f"  R{requirement['id']} {status:<9} {requirement['text']}" + (f"  [{requirement['check']}]" if requirement.get("check") else "  [no check]"))
    if state["constraints"]:
        lines += ["Constraints:", *[f"  - {c['text']}" for c in state["constraints"]]]
    if state["scope"]:
        lines.append("Scope: " + ", ".join(state["scope"]))
    return "\n".join(lines)
