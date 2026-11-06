"""Working toward a goal, next to other agents: an advisory claim table, and a ledger of what done means."""

from __future__ import annotations

import fnmatch
import json
import hashlib
import shlex
import sqlite3
import subprocess
import time
from pathlib import Path

from . import files as filesystem
from .zero_tests import ran_no_tests


_SCHEMA = """
CREATE TABLE IF NOT EXISTS baseline (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS ledger (id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL, owner TEXT, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS claims (path TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def database(root: Path) -> sqlite3.Connection:
    """Shared by every command and agent on this machine for this repository. Explicit transactions, with a long wait for the lock."""
    connection = sqlite3.connect(str(filesystem.state_dir(root) / "occam.db"), timeout=30, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.executescript(_SCHEMA)
    return connection


def _db(root: Path) -> sqlite3.Connection:
    return database(root)


# ---------------------------------------------------------------- coordination


def active_claims(root: Path) -> dict[str, str]:
    try:
        with _db(root) as db:
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
        with _db(root) as db:
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
    with _db(root) as db:
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
    dirty = filesystem.dirty_paths(root)
    lines = []
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
    with _db(root) as db:
        row = db.execute("SELECT value FROM kv WHERE key = 'goal'").fetchone()
    return json.loads(row[0]) if row else None


def _save(root: Path, goal_state: dict) -> None:
    with _db(root) as db:
        db.execute("INSERT OR REPLACE INTO kv VALUES ('goal', ?)", (json.dumps(goal_state),))


def _change_goal(root: Path, change) -> dict | None:
    """Read, change and write in one transaction, so agents adding requirements at once can't lose each other's."""
    with _db(root) as db:
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


def _tree_state(root: Path, paths: list[str] | None = None) -> str:
    """A cheap identity for the working tree's contents, so old evidence can be recognized as stale."""
    digest = hashlib.sha1()
    head = filesystem.run_git(root, "rev-parse", "HEAD")
    if head is not None:
        digest.update(head.encode())
        digest.update((filesystem.run_git(root, "status", "--porcelain=v1") or "").encode())
        for name in filesystem.dirty_paths(root):
            try:
                digest.update((root / name).read_bytes())
            except OSError:
                continue
        return digest.hexdigest()[:16]
    for name in filesystem.list_files(root, paths, filesystem.load_config(root))[:20000]:
        try:
            stat = (root / name).stat()
            digest.update(f"{name}\0{stat.st_size}\0{stat.st_mtime_ns}".encode())
        except OSError:
            continue
    return digest.hexdigest()[:16]


def goal(root: Path, args) -> tuple[str, int]:
    text = " ".join(args.text).strip()
    state = _load(root)
    if args.action == "init":
        if not text:
            return "State the goal: the observable outcome, not the steps.", 2
        head = (filesystem.run_git(root, "rev-parse", "HEAD") or "").strip() or None
        _save(root, {"goal": text, "requirements": [], "constraints": [], "scope": [], "created": time.time(), "base": head, "snapshot": {} if filesystem.in_git(root) else _snapshot(root)})
        return f"Goal set: {text}\nAdd what must be true with `occam goal add \"...\" --check \"command\"`, and limits with `occam goal constrain`.", 0
    if args.action == "clear":
        with _db(root) as db:
            db.execute("DELETE FROM kv WHERE key = 'goal'")
        return "Goal cleared.", 0
    if state is None:
        return "No goal yet. `occam goal init \"the outcome\"` starts one.", 2
    if args.action == "add":
        if not text:
            return "State the requirement as something observable.", 2

        def add(current: dict) -> None:
            current["requirements"].append({"id": len(current["requirements"]) + 1, "text": text, "check": args.check, "where": args.where, "status": "not run", "tree": None, "detail": ""})

        state = _change_goal(root, add)
        return f"R{len(state['requirements'])}: {text}" + ("" if args.check else "  (no check yet, so report it unverified until there is one)"), 0
    if args.action == "constrain":
        if not text and not args.forbid:
            return "State the constraint.", 2
        constraint = {"text": text or f"Don't change {args.forbid}", "forbid": args.forbid}
        _change_goal(root, lambda current: current["constraints"].append(constraint))
        return f"Constraint recorded: {constraint['text']}. Reread at every `goal verify`.", 0
    if args.action == "scope":
        _change_goal(root, lambda current: current.update(scope=args.text))
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


def _run_check(root: Path, command: str, timeout: int) -> tuple[bool, str]:
    try:
        done = subprocess.run(shlex.split(command), cwd=str(root), capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except (OSError, ValueError) as error:
        return False, f"couldn't run: {error}"
    output = (done.stdout + done.stderr).strip().split("\n")
    tail = " / ".join(line.strip() for line in output[-2:] if line.strip())[:200]
    if done.returncode == 0 and ran_no_tests(done.stdout + "\n" + done.stderr):
        return False, "ran zero tests"
    return done.returncode == 0, f"exit {done.returncode}: {tail}"


def _snapshot(root: Path) -> dict[str, str]:
    """Outside git there's no history to compare with, so a goal records what the files were when it began."""
    found = {}
    for name in filesystem.list_files(root, None, {})[:50000]:
        if filesystem.is_plain_file(root / name):
            stat = (root / name).stat()
            found[name] = f"{stat.st_size}:{stat.st_mtime_ns}"
    return found


def _changed_files(root: Path, state: dict, base: str | None) -> list[str]:
    """Everything this work touched, including what it deleted and where renames came from."""
    changed = filesystem.changed_lines(root, base or state.get("base"))
    if changed is None:
        before, now = state.get("snapshot") or {}, _snapshot(root)
        return sorted(name for name in {*before, *now} if before.get(name) != now.get(name))
    deleted, renamed = filesystem.removed_and_renamed(root, base or state.get("base"))
    return sorted({*changed, *deleted, *renamed.values()})


def _verify(root: Path, state: dict, args) -> tuple[str, int]:
    lines = [f"Goal: {state['goal']}"]
    tree = _tree_state(root)
    results: dict[int, dict] = {}
    for requirement in state["requirements"]:
        passed, detail = _run_check(root, requirement["check"], args.timeout) if requirement.get("check") else (False, "no check given")
        status = "verified" if passed else "failed" if requirement.get("check") else "not run"
        results[requirement["id"]] = {"status": status, "detail": detail, "tree": tree if requirement.get("check") else None}

    def record(current: dict) -> None:  # merged rather than overwritten, because checks take time and others may add requirements meanwhile
        for requirement in current["requirements"]:
            requirement.update(results.get(requirement["id"], {}))

    state = _change_goal(root, record)
    failed = 0
    for requirement in state["requirements"]:
        unverified = requirement["status"] != "verified" or requirement["id"] not in results
        failed += unverified
        lines.append(f"  R{requirement['id']} {requirement['status']:<9} {requirement['text']}" + (f"  ({requirement['detail']})" if unverified else ""))
    if not state["requirements"]:
        failed += 1
        lines.append("  No requirements recorded, so nothing is verified.")
    try:
        drift = _scope_problems(root, state, args.base)
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


def _scope_problems(root: Path, state: dict, base: str | None) -> list[str]:
    changed = _changed_files(root, state, base)
    problems = []
    for constraint in state["constraints"]:
        pattern = constraint.get("forbid")
        if pattern:
            hit = [path for path in changed if fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("*/") + "/")]
            if hit:
                problems.append(f"VIOLATED: {constraint['text']}: {', '.join(hit[:5])}")
    if state["scope"]:
        outside = [path for path in changed if not any(fnmatch.fnmatch(path, s) or path == s or path.startswith(s.rstrip("/") + "/") for s in state["scope"])]
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
