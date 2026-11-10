"""Limits on what a turn does without a person, the owner's calls on 2026-11-08 (DESIGN `session-recall-owner-calls`): a release while a
check this turn ran is still failing is confirmed by a person, and what the request itself rules out is recorded as goal limits for `gate`.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import re

from occam_commands import ci_status_failed, ci_status_of, narrowed_run, output_text, release_of, run_by
from session_state import Session, record
from shell_writes import project_root, shell_steps


def release_over_a_failure(command: str, event: dict, session: Session) -> str | None:
    """Why a person should confirm this release, or None. Checks joined to it by `&&` earlier in the command decide it again, so the
    release isn't asked about when they cover every failure left; `;`, `||`, a pipe or `!` would release whatever a check showed."""
    release = next((name for name in (release_of(step.words) for step in shell_steps(command, event) if step.words) if name), None)
    if not release:
        return None
    checks = [e for e in session.turn if e.get("kind") == "check" and not e.get("not_this_code")]
    failing, red = _unresolved(checks), _red_statuses(session)
    if not failing and not red or _gated_away(command, failing, red):
        return None
    return f"`{release}` releases this work, and a check that failed this turn hasn't passed since."


def _red_statuses(session: Session) -> list[str]:
    latest: dict = {}  # each status query's latest result
    for entry in session.turn:
        if entry.get("kind") == "ci_status":
            latest[entry.get("name")] = entry.get("passed")
    return [name for name, passed in latest.items() if passed is False]


def _gated_away(command: str, failing: list[str], red: list[str]) -> bool:
    """The checks `&&` puts ahead of the release cover every failure and red status left."""
    gates = _gates(command)
    return gates is not None and all(any(_covers(gate, run) for gate in gates) for run in failing) and set(red) <= {ci_status_of(gate.split()) for gate in gates}


def _gates(command: str) -> list[str] | None:
    """The commands joined by `&&` ahead of the release, which must pass for it to run, or None if anything else joins them."""
    text = re.sub(r"&&\s*\n", "&& ", re.sub(r"\\\n", " ", command))
    parts = re.split(r"(&&|\|\||;|\n|(?<![|&])[|&](?![|&]))", text)
    segments, operators = [part.strip() for part in parts[0::2]], parts[1::2]
    at = next((index for index, segment in enumerate(segments) if release_of(segment.split())), None)
    if not at or any(operator != "&&" for operator in operators[:at]) or any(segment.startswith("!") for segment in segments[:at]):
        return None
    return segments[:at]


_SCOPE_FLAGS = {"--all-features", "--workspace", "--all", "--all-targets", "--features", "-F", "--race", "-race", "-tags", "--tags"}
_SUBCOMMANDS = {"go", "cargo", "npm", "yarn", "pnpm", "bun", "deno", "make", "just", "rake", "mvn", "mvnw", "gradle", "gradlew", "dotnet", "mix", "swift"}
_WHOLE = {".", "./...", "...", "./"}


def _covers(passed: str, failed: str) -> bool:
    """Does this passing run cover what that failed one ran? The same run, or a whole run of the same tool and subcommand, from the same
    folder, with the same scope flags and values. When in doubt it doesn't, and a person is asked."""
    if passed == failed:
        return True
    (prefix, passed_words), (failed_prefix, failed_words) = _parts(passed), _parts(failed)
    (program, args), (failed_program, failed_args) = _unwrapped(passed_words), _unwrapped(failed_words)
    if prefix != failed_prefix or program != failed_program or narrowed_run(passed_words) or _scope(args) != _scope(failed_args):
        return False
    positional, failed_positional = _plain(args), _plain(failed_args)
    sub = 1 if program in _SUBCOMMANDS else 0
    return positional[:sub] == failed_positional[:sub] and all(target in _WHOLE for target in positional[sub:])


def _parts(text: str) -> tuple[str, list[str]]:
    prefix, _, last = text.rpartition(" && ")  # a `cd` before the run is part of what it ran
    return prefix, last.split()


def _unwrapped(words: list[str]) -> tuple[str, list[str]]:
    program, args = run_by(words)
    return (args[0].rsplit("/", 1)[-1], args[1:]) if program in ("npx", "bunx") and args else (program, args)


def _scope(args: list[str]) -> list[str]:
    return sorted(f"{arg} {args[index + 1] if arg in ('--features', '-F', '-tags', '--tags') and index + 1 < len(args) else ''}" for index, arg in enumerate(args)
                  if arg.split("=", 1)[0] in _SCOPE_FLAGS)


def _plain(args: list[str]) -> list[str]:
    return [arg for arg in args if not arg.startswith("-")]


def _unresolved(checks: list[dict]) -> list[str]:
    """Runs that failed with no later pass covering them. A subagent probing for failures is doing its job, so its failures don't count."""
    failing: list[str] = []
    for check in checks:
        runs = [text for text, _ in check.get("runs") or []]
        if not check.get("passed"):
            failing += [] if check.get("agent") else runs
            continue
        failing = [run for run in failing if not any(_covers(passed, run) for passed in runs)]
    return failing


def record_statuses(event: dict, commands: list[list[str]], succeeded: bool) -> None:
    """`gh pr checks`, a smoke run and the like, which a release over a red one ignores: the latest result of each."""
    statuses = [(words, ci_status_of(words)) for words in commands]
    if not any(name for _, name in statuses):
        return
    code = int((re.search(r"\bExit code (\d+)", str(event.get("error") or "")) or [None, "0" if succeeded else "1"])[1])
    said = output_text(event.get("tool_response")) + str(event.get("error") or "")
    for words, name in statuses:
        if name:
            record(event, kind="ci_status", name=name, passed=not ci_status_failed(words, code, said))


def limit_notes(event: dict, words: str, skip: bool) -> list[str]:
    """Record what the user's own words rule out, for this session. Not on a read-only turn or at the guard level, where `skip` is set."""
    if skip:
        return []
    try:
        from occam_tools import workflow  # on sys.path through scale_notes, and imported late so a problem there fails open

        recorded = workflow.record_stated_limits(project_root(event), words, str(event.get("session_id") or ""))
    except Exception:  # occam: ignore[swallowed-exception] a limit that couldn't be recorded is a check lost, not a reason to fail the prompt
        return []
    return [f"occam recorded what this request rules out as goal limits for this session, which `gate` and `goal verify` check: {', '.join(recorded)}. "
            "`occam goal clear` lifts them if the request changes."] if recorded else []
