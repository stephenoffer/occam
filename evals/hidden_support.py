"""pytest plugin giving evaluator-owned checks access to one finished run.

Loaded by grade_workspaces.py with `-p hidden_support`. Checks should go through
entry points the case's prompt fixes, so a valid alternative design does not fail.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

TEST_TIMEOUT_SECONDS = 300


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Turn a hang in agent-written code into a named failure. Repeats, to break out of cleanup loops."""
    def expire(signum, frame):
        raise TimeoutError(f"{item.name} exceeded {TEST_TIMEOUT_SECONDS}s")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, TEST_TIMEOUT_SECONDS, 5)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.fixture(scope="session")
def ws() -> Path:
    return Path(os.environ["EVAL_WORKSPACE"])


@pytest.fixture(scope="session")
def final_message() -> str:
    path = os.environ.get("EVAL_FINAL_MESSAGE", "")
    return Path(path).read_text() if path and Path(path).exists() else ""


@pytest.fixture(scope="session")
def tool_calls() -> list[dict]:
    """Every tool the agent called, in order: {"name", "input", "is_error", "result"}."""
    path = os.environ.get("EVAL_TRACE", "")
    if not path or not Path(path).exists():
        return []
    calls, by_id = [], {}
    # Split on newlines only: str.splitlines() also breaks on characters like U+2028 inside JSON strings.
    for line in Path(path).read_text().split("\n"):
        if not line.strip():
            continue
        message = json.loads(line)
        content = message.get("message", {}).get("content") if isinstance(message.get("message"), dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if message.get("type") == "assistant" and block.get("type") == "tool_use":
                call = {"name": block["name"], "input": block["input"], "is_error": False, "result": ""}
                calls.append(call)
                by_id[block.get("id")] = call
            elif message.get("type") == "user" and block.get("type") == "tool_result" and block.get("tool_use_id") in by_id:
                text = block.get("content")
                if isinstance(text, list):
                    text = " ".join(part.get("text", "") for part in text if isinstance(part, dict))
                by_id[block["tool_use_id"]].update(is_error=bool(block.get("is_error")), result=str(text or ""))
    return calls


@pytest.fixture(scope="session")
def git(ws):
    def run(*args: str) -> str:
        done = subprocess.run(
            [os.environ.get("EVAL_GIT", "git"), *args],
            cwd=ws, capture_output=True, text=True, timeout=60,
        )
        assert done.returncode == 0, f"git {args}: {done.stderr}"
        return done.stdout
    return run


@pytest.fixture(scope="session")
def py(ws):
    """Run the workspace's Python entry point in a subprocess, from the workspace."""
    def run(*args: str, timeout: float = 60, **kwargs) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": str(ws), "PYTHONDONTWRITEBYTECODE": "1", **kwargs.pop("env", {})}
        return subprocess.run(
            [sys.executable, *args], cwd=ws, capture_output=True, text=True,
            timeout=timeout, env=env, **kwargs,
        )
    return run
