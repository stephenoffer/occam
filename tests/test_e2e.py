"""occam through its real entry points on a small real project: every command, every query, and one session through the hook as hooks.json wires it.

Other test files go deep on one part. This one answers whether the whole thing works, so each row states what a user should see, not just that nothing crashed.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OCCAM = ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam.py"
HOOKS = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]
PYTEST = f"{sys.executable} -m pytest -q"


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """A small repository with known defects, one commit and one uncommitted change."""
    base = tmp_path_factory.mktemp("e2e")
    repo = base / "repo"
    files = {
        "app/__init__.py": "",
        "app/prices.py": '"""Prices."""\n\n\ndef discounted(price, percent):\n    if percent >= 100:\n        return 0\n    return price - price * percent / 100\n\n\ndef refund(order):\n    pass\n',
        "app/db.py": "def lookup(conn, name):\n    return conn.execute(\"select * from t where n = '%s'\" % name).fetchall()\n",
        "tests/test_prices.py": "from app.prices import discounted\n\n\ndef test_discount():\n    assert discounted(100, 10) is not None\n",
        "scripts/run.sh": "#!/bin/bash\nrm -rf $1/build\n",
        "README.md": "# Demo\n\nCall `discounted` and `missing_name`. See [nope](nope.md).\n",
        "pyproject.toml": '[project]\nname = "demo"\nversion = "0.1"\ndependencies = ["requests"]\n',
        "conftest.py": "",
    }
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    env = {**os.environ, "HOME": str(base), "XDG_CACHE_HOME": str(base / "cache"), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("OCCAM_STATE_DIR", None)  # a test run may set it, and this project's state has to be its own
    for git in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "first"]):
        subprocess.run(["git", *git], cwd=repo, env=env, check=True, capture_output=True)
    (repo / "app" / "prices.py").write_text(files["app/prices.py"].replace("    pass\n", "    # TODO: implement\n    return None\n"))
    return repo, env


def occam(project, *args, stdin=""):
    repo, env = project
    done = subprocess.run([sys.executable, str(OCCAM), *args], cwd=repo, env=env, input=stdin, capture_output=True, text=True, timeout=120)
    assert "Traceback (most recent call last)" not in done.stdout + done.stderr, done.stdout + done.stderr
    return done.returncode, done.stdout + done.stderr


# Each row: the arguments, the exit status, and what the answer must say. In order, because some build on earlier ones.
ANSWERS = [
    (("--version",), 0, r"^\d+\.\d+\.\d+"),
    (("map",), 0, r"small repository|lines in"),
    (("map", "app", "--isolated"), 0, r"lines in"),
    (("scan",), 0, r"sql-injection"),
    (("scan", "app", "--format", "json"), 0, r'"rule": "sql-injection"'),
    (("scan", "--format", "sarif"), 0, r'"version": "2\.1\.0"'),
    (("scan", "--format", "md"), 0, r"sql-injection"),
    (("scan", "--changed"), 0, r"prices\.py"),
    (("scan", "--diff", "HEAD"), 0, r"prices\.py"),
    (("scan", "--fail-on", "critical"), 1, r"sql-injection"),
    (("rules",), 0, r"sql-injection"),
    (("rules", "sql-injection"), 0, r"sql-injection"),
    (("tools",), 0, r"ruff|Not installed|installed"),
    (("deps",), 0, r"requests"),
    (("baseline", "write"), 0, r"\d+ findings|Accepted|Baseline"),
    (("baseline", "show"), 0, r"\d+"),
    (("scan", "--new-only"), 0, r"0 findings|No findings"),
    (("partition",), 0, r"shard"),
    (("partition", "--mode", "write"), 0, r"shard|writer|agents"),
    (("golden", "record", "ok", "--", sys.executable, "-c", "print(1)"), 0, r"[Rr]ecorded"),
    (("golden", "check", "ok"), 0, r"same|[Uu]nchanged|[Mm]atch"),
    (("golden", "record", "rooted", "--root", ".", "--timeout", "30", "--", sys.executable, "-c", "print(2)"), 0, r"[Rr]ecorded"),
    (("golden", "check", "rooted", "--timeout", "30"), 0, r"same|[Uu]nchanged|[Mm]atch"),
    (("mutate", "--cmd", PYTEST, "app/prices.py"), 1, r"deliberate breakages"),
    (("bench", "--cmd", f'{sys.executable} -c "print(sum(range({{n}})))"', "--sizes", "10,100", "--repeat", "1"), 0, r"100"),
    (("coord", "status"), 0, r"uncommitted"),
    (("coord", "claim", "app/prices.py", "--owner", "e2e"), 0, r"e2e holds 1"),
    (("coord", "check", "app/prices.py", "--owner", "other"), 1, r"e2e"),
    (("coord", "release", "app/prices.py", "--owner", "e2e"), 0, r"[Rr]eleased"),
    (("goal", "init", "works"), 0, r"works"),
    (("goal", "add", "tests pass", "--check", PYTEST), 0, r"\w+"),
    (("goal", "status"), 0, r"tests pass"),
    (("goal", "verify"), 0, r"pass|verified"),
    (("goal", "clear"), 0, r"\w+"),
    (("gate",), 0, r"changed files"),
    (("gate", "--strict"), 1, r"NOT READY"),
    (("docs", "README.md"), 1, r"missing_name"),
    (("query", "size"), 0, r"python"),
    (("query", "commands"), 0, r"\w+"),
    (("query", "entry"), 0, r"\w+"),
    (("query", "outline", "app/prices.py"), 0, r"discounted"),
    (("query", "find", "discounted"), 0, r"app/prices\.py"),
    (("query", "grep", "price", "--in", "code"), 0, r"app/prices\.py"),
    (("query", "functions"), 0, r"discounted|refund|lookup"),
    (("query", "api"), 0, r"discounted"),
    (("query", "boundaries"), 0, r"database"),
    (("query", "graph"), 0, r"\w+"),
    (("query", "graph", "app/prices.py"), 0, r"test_prices"),
    (("query", "impact", "app/prices.py"), 0, r"test_prices"),
    (("query", "impact", "--changed"), 0, r"test_prices"),
    (("query", "tests"), 0, r"test files"),
    (("query", "tests", "app/prices.py"), 0, r"test_prices"),
    (("query", "history"), 0, r"\w+"),
    (("query", "markers"), 0, r"\w+"),
    (("query", "leaks"), 0, r"\w+"),
    (("query", "size", "--format", "json"), 0, r'"files"'),
    (("design", "check"), 0, r"No design doc"),
    (("design", "init"), 0, r"Wrote DESIGN\.md"),
    (("design", "decide", "use-sqlite", "Use sqlite", "--why", "it is enough", "--applies", "app"), 0, r"use-sqlite"),
    (("design", "for", "app/prices.py"), 0, r"[Uu]se.sqlite"),
    (("design", "check"), 1, r"placeholder"),
]


def test_every_command_gives_its_answer(project):
    wrong = []
    for args, status, shows in ANSWERS:
        code, output = occam(project, *args)
        if code != status or not re.search(shows, output):
            wrong.append(f"{' '.join(args)}: exit {code}, wanted {status} and /{shows}/\n{output[-400:]}")
    assert not wrong, "\n\n".join(wrong)


def test_every_command_and_query_is_in_that_list():
    """So a new command can't arrive without an end-to-end row."""
    sys.path.insert(0, str(OCCAM.parent))
    from occam_tools.cli import _parser

    def choices(parser):
        return next(action.choices for action in parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict))

    commands = choices(_parser())
    tried = {args[0] for args, _, _ in ANSWERS} - {"--version"}
    tried_queries = {args[1] for args, _, _ in ANSWERS if args[0] == "query"}
    assert set(commands) == tried
    assert set(choices(commands["query"])) == tried_queries


@pytest.mark.parametrize("snippet", ["import os\n", "import foozle\n", "import requests\nrequests.get('x')\n", "def f(:\n"])
def test_a_snippet_on_stdin_scans_whatever_it_imports(project, snippet):
    code, output = occam(project, "scan", "--stdin", stdin=snippet)
    assert code == 0 and "occam scan" in output


@pytest.mark.parametrize("args", [
    ("scan", "nosuch"), ("map", "nosuch"), ("partition", "nosuch"), ("query", "size", "nosuch"), ("mutate", "--cmd", "true", "nosuch"), ("tools", "nosuch"),
])
def test_a_path_that_isnt_there_is_never_a_clean_answer(project, args):
    code, output = occam(project, *args)
    assert code == 2 and "No such path: nosuch" in output


@pytest.mark.parametrize("args", [
    ("golden", "record", "x", "--timeout", "abc", "--", "true"),
    ("mutate", "--cmd", "true", "--max", "0", "app/prices.py"),
    ("bench", "--cmd", "no-such-program-here {n}", "--sizes", "1"),
    ("bench", "--cmd", "true {n}", "--sizes", "1,a"),
    ("bench", "--cmd", "true {n}", "--sizes", "1", "--repeat", "0"),
    ("bench", "--cmd", 'x " {n}', "--sizes", "1"),
    ("golden", "record", "z", "--normalize", "(", "--", "true"),
    ("golden", "record", "z", "--timeout", "\u00b2", "--", "true"),
    ("mutate", "--cmd", ""),
    ("baseline", "write", "--out", "/nonexistent/folder/x"),
    ("tools", "--run", ".", "/"),
])
def test_bad_input_gets_a_plain_refusal(project, args):
    code, output = occam(project, *args)
    assert code == 2 and output.strip()


def test_a_baseline_that_isnt_one_can_only_make_a_scan_stricter(project, tmp_path):
    bad = tmp_path / "baseline.json"
    bad.write_text("5")
    code, output = occam(project, "scan", "--baseline", str(bad))
    assert code == 0 and "Couldn't read" in output and "sql-injection" in output  # everything counts as new, so `--fail-on` still fails


def test_golden_check_honours_its_timeout(project):
    code, _ = occam(project, "golden", "record", "slow", "--", sys.executable, "-c", "import time; time.sleep(3)")
    assert code == 0
    code, output = occam(project, "golden", "check", "slow", "--timeout", "1")
    assert code == 2 and "didn't finish in 1s" in output


def test_state_that_cant_be_read_doesnt_take_the_gate_down(project, tmp_path):
    repo, env = project
    (tmp_path / "home").mkdir()
    cache = tmp_path / "cache"
    fresh = (repo, {**env, "HOME": str(tmp_path / "home"), "XDG_CACHE_HOME": str(cache)})
    assert occam(fresh, "coord", "claim", "app/db.py", "--owner", "me")[0] == 0
    for database in cache.rglob("occam.db"):
        database.write_bytes(b"this is not a database" * 100)
    code, output = occam(fresh, "gate")
    assert code in (0, 1) and "changed files" in output
    code, output = occam(fresh, "baseline", "show")
    assert code == 2 and "can't be read" in output


# ---------------------------------------------------------------- one session through hooks.json

def hook_command(event: str) -> list[str]:
    """The program and arguments Claude Code would run for this event, read from the real configuration."""
    entry = HOOKS[event][0]["hooks"][0]
    return [entry["command"], *(arg.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT / "plugin")) for arg in entry["args"])]


@pytest.fixture()
def session(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT / "plugin"), "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"), "CLAUDE_PROJECT_DIR": str(folder)}
    env.pop("OCCAM_HOOKS", None)

    def send(hook_event: str, env=env, **fields):
        done = subprocess.run(hook_command(hook_event), input=json.dumps({"session_id": "e2e", "cwd": str(folder), **fields}), capture_output=True, text=True, env=env, timeout=30)
        assert done.returncode == 0 and "failed open" not in done.stderr, done.stderr
        return (json.loads(done.stdout) if done.stdout.strip() else {}).get("hookSpecificOutput", {})

    send.folder = folder
    send.env = env
    return send


def edit(path: Path, old: str = "a = 1\n", new: str = "a = 2\n") -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}


def test_a_whole_session_through_the_configured_hooks(session):
    code = session.folder / "billing.py"
    code.write_text("a = 1\n")

    assert "occam" in session("SessionStart", source="startup")["additionalContext"]
    session("UserPromptSubmit", prompt="Change the billing rounding.")

    held = session("PreToolUse", **edit(code))
    assert held["permissionDecision"] == "deny" and "skill" in held["permissionDecisionReason"]

    session("PostToolUse", tool_name="Skill", tool_input={"skill": "occam:occam"})
    allowed = session("PreToolUse", **edit(code))
    assert allowed.get("permissionDecision") != "deny"
    code.write_text("a = 2\n")
    session("PostToolUse", **edit(code), tool_response={})

    sent_back = session("Stop", last_assistant_message="Done. All tests pass.")
    assert "No check has run since the last code edit" in sent_back["additionalContext"]
    assert "no check passed during this turn" in sent_back["additionalContext"]
    assert "code-reviewer" in sent_back["additionalContext"]  # billing handles money, so it gets the reviewer

    session("PostToolUse", tool_name="Bash", tool_input={"command": "python3 -m pytest -q"}, tool_response={"stdout": "1 passed in 0.01s"})
    session("PostToolUse", tool_name="Agent", tool_input={"subagent_type": "occam:code-reviewer"}, tool_response={})
    session("SubagentStop", agent_id="r1", agent_type="occam:code-reviewer")
    assert session("Stop", last_assistant_message="Changed the rounding. 1 passed.") == {}


def test_the_hooks_really_reach_the_scanner(session):
    """Hooks fail open, so a broken import or a moved name would silently turn this off and nothing else would say so."""
    code = session.folder / "lookup.py"
    code.write_text("x = 1\n")
    session("UserPromptSubmit", prompt="Add a lookup.")
    session("PostToolUse", tool_name="Skill", tool_input={"skill": "occam:occam"})
    session("PreToolUse", **edit(code))
    code.write_text("def lookup(db, name):\n    return db.execute(f\"select * from t where n = '{name}'\").fetchall()\n")
    said = session("PostToolUse", **edit(code), tool_response={})
    assert "sql-injection" in said["additionalContext"]
    assert "The scanner sees these" in session("Stop", last_assistant_message="Added it.")["additionalContext"]


def test_what_the_hooks_stop_outright(session):
    session("UserPromptSubmit", prompt="Tidy this up.")
    asked = session("PreToolUse", tool_name="Bash", tool_input={"command": "git reset --hard"})
    assert asked["permissionDecision"] == "ask" and "git reset" in asked["permissionDecisionReason"]
    web = session("PreToolUse", tool_name="WebFetch", tool_input={"url": "https://example.com/?k=ghp_" + "a" * 36})
    assert web["permissionDecision"] == "deny" and "GitHub token" in web["permissionDecisionReason"]

    session("UserPromptSubmit", prompt="Review only: what's wrong with this module?")
    held = session("PreToolUse", **edit(session.folder / "m.py"))
    assert held["permissionDecision"] == "deny" and "review-only" in held["permissionDecisionReason"]
    assert session("PreToolUse", tool_name="Bash", tool_input={"command": "sed -i '' 's/a/b/' m.py"})["permissionDecision"] == "deny"


def test_a_small_edit_goes_ahead_with_its_rule_beside_it(session):
    code = session.folder / "report.py"
    code.write_text("label = 'items'\n")
    session("UserPromptSubmit", prompt="It prints `1 items`, it should say `1 item`.")
    said = session("PreToolUse", **edit(code, "label = 'items'\n", "label = 'item'\n"))
    assert "permissionDecision" not in said and "everywhere it occurs" in said["additionalContext"]  # the rule card, since no session start was heard


def test_the_hooks_step_aside_when_asked_and_when_broken(session):
    code = session.folder / "billing.py"
    code.write_text("a = 1\n")
    assert session("PreToolUse", env={**session.env, "OCCAM_HOOKS": "off"}, **edit(code)) == {}
    done = subprocess.run(hook_command("PreToolUse"), input="not json", capture_output=True, text=True, env=session.env, timeout=30)
    assert done.returncode == 0 and done.stdout == "" and "failed open" in done.stderr
