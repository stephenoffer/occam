#!/usr/bin/env python3
"""Optional Stop hook: run one fast check before an agent finishes.

    verify_on_stop.py --timeout 120 -- ruff check .

The command comes only from this argv, which you put in your own hook config. It is
never read from repository content and never goes through a shell. It runs from the
repository root. Give it a fast check and leave expensive suites to CI, because this
runs each time the agent stops with local changes.

Protocol, the subset documented by both Claude Code and Codex:
  exit 0, no stdout                 let the agent finish
  exit 0, {"decision": "block",     keep working, with the reason as feedback
           "reason": "..."}

JSON rather than exit 2, because Claude Code treats exit 2 as non-blocking when stderr
reports a missing file, which would let a failed check pass silently.

Known gaps: a clean tree skips the check, so work the agent has already committed is not
checked here, and neither is a change only inside a submodule's working tree, because
asking the submodule would run what its own config names. This is a guardrail, not proof
of correctness and not a security boundary.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

import argparse
import json
import os
import re
import subprocess
import sys

# A repository delivered with its .git folder can name programs for git to run. This script gets copied
# on its own, so it carries the list itself, and a test keeps it in step with occam_tools/files.py.
GIT_SAFETY = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.sshCommand=false", "-c", "diff.external=", "-c", "log.showSignature=false",
              "-c", "gpg.program=false", "-c", "core.pager=cat", "-c", "core.quotePath=false", "-c", "diff.mnemonicPrefix=false", "-c", "diff.noprefix=false",
              "-c", "status.showUntrackedFiles=all", "-c", "protocol.allow=never", "-c", "diff.ignoreSubmodules=dirty", "-c", "submodule.recurse=false",
              "-c", "status.submoduleSummary=false", "-c", "diff.submodule=short", "--no-pager"]
# -c protocol.allow loses to a repository's own protocol.<name>.allow, and GIT_NO_LAZY_FETCH does nothing on git 2.39. GIT_ALLOW_PROTOCOL outranks both.
# It lists what to allow. No URL can use `_` and no alias can answer to it, where `none` would allow an alias.remote-none.
GIT_ENVIRONMENT = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "_"}
DRIVER_KEY = re.compile(r"^(filter|diff|merge)\.(.*)\.(clean|smudge|process|command|textconv|driver|required)$", re.I | re.S)
OUTPUT_LINES = 40
SECRET = re.compile(r"(?i)((?:api[_-]?key|token|secret|password|passwd)\s*[=:]\s*)\S+")
NOT_AN_INSTRUCTION = (
    "\n\nThis check authorizes no edits. If this turn was review-only, or these failures "
    "aren't from your change, report them instead of fixing them."
)


def block(message: str) -> int:
    print(json.dumps({"decision": "block", "reason": SECRET.sub(r"\1[redacted]", message)}))
    return 0


def blanked_drivers(cwd: str | None) -> dict[str, str]:
    """Filter and diff drivers are named freely, even empty, not UTF-8 or with = in the name, so blank each one through the environment.

    Reading config runs nothing. Raises OSError if it can't be read, because the drivers would then stay on.
    """
    # GIT_CONFIG would point only this listing at one file, while the real command still reads the repository's.
    listing = {name: value for name, value in os.environ.items() if name != "GIT_CONFIG"}
    listed = subprocess.run(["git", *GIT_SAFETY, "config", "--list", "--name-only", "--null"], cwd=cwd, capture_output=True, timeout=10, env=listing)
    if listed.returncode != 0:
        raise OSError(f"git config exited with {listed.returncode}")
    drivers = [match for match in map(DRIVER_KEY.match, map(os.fsdecode, listed.stdout.split(b"\0"))) if match]
    inherited = int(os.environ.get("GIT_CONFIG_COUNT") or 0)  # settings already passed this way have to keep working
    settings = {"GIT_CONFIG_COUNT": str(inherited + len(drivers))}
    for index, match in enumerate(drivers, inherited):
        settings[f"GIT_CONFIG_KEY_{index}"] = match.group(0)
        settings[f"GIT_CONFIG_VALUE_{index}"] = "false" if match.group(3).lower() == "required" else ""
    return settings


def git(cwd: str | None, *args: str) -> str | None:
    """Output of a git command, or None if it could not say."""
    try:
        environment = {**os.environ, **GIT_ENVIRONMENT, **blanked_drivers(cwd)}
        done = subprocess.run(["git", *GIT_SAFETY, *args], cwd=cwd, capture_output=True, text=True, errors="replace", timeout=30, env=environment)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def main(argv: list[str] | None = None, stdin: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=120, help="seconds before the check counts as not completed")
    parser.add_argument("command", nargs="+", help="check to run, after --")
    args = parser.parse_args(argv)

    try:
        event = json.loads(sys.stdin.read() if stdin is None else stdin)
    except ValueError:
        event = {}
    if not isinstance(event, dict):
        event = {}
    # Already continued once for this stop: let it finish rather than loop.
    if event.get("stop_hook_active"):
        return 0

    cwd = event.get("cwd")
    # The session's cwd can follow a `cd`, and a check like `ruff check .` shouldn't pass on one subdirectory.
    root = git(cwd, "rev-parse", "--show-toplevel")
    where = root.strip() if root else cwd
    # On the command line, because a repository's submodule.<name>.ignore outranks -c diff.ignoreSubmodules.
    if git(where, "status", "--porcelain", "--ignore-submodules=dirty") == "":
        return 0

    name = " ".join(args.command)
    try:
        done = subprocess.run(args.command, cwd=where, capture_output=True, text=True, errors="replace",
                              timeout=args.timeout)
    except subprocess.TimeoutExpired:
        return block(f"Check not completed: `{name}` exceeded {args.timeout:g}s. Its result is unknown.")
    except OSError as error:
        return block(f"Check not run: `{name}` could not start ({error}). Report it as not run, not as passing.")
    if done.returncode == 0:
        return 0
    tail = "\n".join((done.stdout + done.stderr).splitlines()[-OUTPUT_LINES:])
    return block(f"Check failed with exit code {done.returncode}: `{name}`\n{tail}{NOT_AN_INSTRUCTION}")


if __name__ == "__main__":
    raise SystemExit(main())
