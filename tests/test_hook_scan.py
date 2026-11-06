"""The hooks' use of the scanner: mention what this work introduced, once, and nothing it didn't."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_occam_hook import Agent

ROOT = Path(__file__).resolve().parents[1]
CODEX_HOOK = ROOT / "plugin" / "hooks" / "codex_hook.py"
STUB = "def charge(card):\n    pass\n"
CLEAN = "def charge(card):\n    return card.pay()\n"


@pytest.fixture
def agent(tmp_path):
    made = Agent(tmp_path)
    made.prompt("change the billing helper")
    made.load()
    return made


def additional(result):
    return (result or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


def write(agent, name, content):
    path = Path(agent.path(name))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_a_clean_edit_says_nothing(agent):
    write(agent, "app.py", CLEAN)
    agent.try_edit("app.py")
    assert "occam scan" not in additional(agent.edit("app.py"))


def test_a_stub_introduced_by_an_edit_is_mentioned_once(agent):
    write(agent, "app.py", CLEAN)
    agent.try_edit("app.py")
    write(agent, "app.py", STUB)
    note = additional(agent.edit("app.py"))
    assert "stub-body" in note and "app.py:1" in note
    assert "occam scan" not in additional(agent.edit("app.py")), "mentioned once"


def test_what_was_already_there_isnt_blamed_on_this_edit(agent):
    write(agent, "app.py", STUB)
    agent.try_edit("app.py")
    write(agent, "app.py", STUB + "\n\ndef other():\n    return 1\n")
    assert "occam scan" not in additional(agent.edit("app.py"))


def test_a_new_file_is_all_new(agent):
    agent.try_edit("fresh.py")
    write(agent, "fresh.py", STUB)
    assert "stub-body" in additional(agent.edit("fresh.py"))


def test_stop_sends_back_for_what_is_still_there(agent):
    write(agent, "app.py", CLEAN)
    agent.try_edit("app.py")
    write(agent, "app.py", STUB)
    agent.edit("app.py")
    agent.bash("python3 -m pytest -q", output="1 passed")
    assert "stub-body" in additional(agent.stop())


def test_an_audit_is_told_what_the_scanner_still_raises_in_files_it_changed(tmp_path):
    made = Agent(tmp_path)
    made.prompt("audit this repo and fix what you can")
    made.load("occam:occam-audit")
    write(made, "app.py", 'DEBUG = bool(os.environ.get("APP_DEBUG", False))\n')
    made.try_edit("app.py")
    made.edit("app.py")
    made.bash("python3 -m pytest -q", output="1 passed")
    note = additional(made.stop())
    assert "still raises" in note and "env-flag-truthy" in note and "it isn't" in note


def test_other_work_is_not_told_about_findings_it_did_not_add(agent):
    write(agent, "app.py", 'DEBUG = bool(os.environ.get("APP_DEBUG", False))\n')
    agent.try_edit("app.py")
    agent.edit("app.py")
    agent.bash("python3 -m pytest -q", output="1 passed")
    assert "still raises" not in additional(agent.stop())


def test_stop_is_quiet_once_it_is_fixed(agent):
    write(agent, "app.py", CLEAN)
    agent.try_edit("app.py")
    write(agent, "app.py", STUB)
    agent.edit("app.py")
    write(agent, "app.py", CLEAN)
    agent.edit("app.py")
    agent.bash("python3 -m pytest -q", output="1 passed")
    assert "scanner sees" not in additional(agent.stop())


def test_stop_continues_only_once(agent):
    write(agent, "app.py", CLEAN)
    agent.try_edit("app.py")
    write(agent, "app.py", STUB)
    agent.edit("app.py")
    assert agent.stop(stop_hook_active=True) is None


def test_size_note_and_scan_note_both_arrive(agent):
    write(agent, "big.py", CLEAN)
    agent.try_edit("big.py")
    write(agent, "big.py", STUB + "x = 1\n" * 1100)
    note = additional(agent.edit("big.py"))
    assert "stub-body" in note and "lines" in note


def test_a_broken_scanner_fails_open(agent, monkeypatch):
    write(agent, "app.py", CLEAN)
    agent.env["PYTHONPATH"] = str(Path(agent.project))
    Path(agent.project, "occam_tools").mkdir()
    Path(agent.project, "occam_tools", "__init__.py").write_text("raise RuntimeError('broken')\n")
    agent.try_edit("app.py")
    write(agent, "app.py", STUB)
    agent.edit("app.py")


@pytest.mark.parametrize("prompt, held", [
    ("audit this repository", True),
    ("Please audit the billing service for problems", True),
    ("assess this codebase", True),
    ("Can you audit this repo?", True),
    ("Hey, audit this", True),
    ("What's wrong with this code?", True),
    ("Audit the address parser", True),
    ("audit this and then go ahead and fix it", False),
    ("audit the log format", True),
    ("look at the audit trail code", False),
    ("Implement login, audit entries go to Kafka.", False),
    ("What's wrong with this test? Make it pass.", False),
    ("Add a retry. Assess failures by status code.", False),
    ("Run an audit", True),
    ("Refactor this without making any changes to behavior", False),
    ("Write tests for foo.py without changing the code.", False),
    ("Fix the bug. Don't make any changes to public APIs.", False),
    ("Audit logging is broken on the orders page", False),
    ("Add a review-only role to the admin panel", False),
    ("Speed up the parser. What's wrong with the old one is it's slow.", False),
    ("Perform a security audit of this repo", True),
    ("I want an audit of this code", True),
    ("Let's audit this repo", True),
    ("Review this and don't change anything", True),
    ("Plan only: how would you add caching?", True),
    ("Write a plan for the migration, don't change any code", True),
    ("Make a plan. Don't change any files.", True),
    ("Fix nothing, just review this", True),
    ("Change nothing, review only", True),
    ("Review only. Add your findings to the report", True),
    ("Do not edit any files", True),
    ("Explain this function. Don't make any changes.", True),
    ("audit-only please", True),
    ("Go ahead and audit", True),
    ("Audit the fixtures", True),
    ("audit this repository and fix what you find", False),
    ("audit and clean up the service", False),
    ("fix the audit log", False),
    ("add an audit trail to orders", False),
])
def test_an_audit_without_a_repair_is_read_only(tmp_path, prompt, held):
    made = Agent(tmp_path)
    made.prompt(prompt)
    made.load()
    made.read_reference("security")
    result = made.try_edit("app.py")
    reason = (result or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert ("review-only" in reason) == held, reason


def test_occams_own_writers_are_held_on_a_read_only_turn(tmp_path):
    made = Agent(tmp_path)
    made.prompt("audit this repository")
    made.load()
    tool = ROOT / "plugin/skills/occam/scripts/occam.py"
    (made.project / "build").mkdir()
    for command in (f"python3 {tool} fix --apply", f"python3 {tool} golden record x -- rm -rf build", f"python3 {tool} baseline write --out b.py"):
        reason = (made.try_bash(command) or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        assert "review-only" in reason, command
    assert made.try_bash(f"python3 {tool} scan") is None
    assert made.try_bash(f"python3 {tool} fix") is None


def test_a_file_too_big_to_scan_first_isnt_blamed_on_the_edit(agent):
    secret = 'API_KEY = "abc123def456ghi789"\n'
    write(agent, "big.py", secret + "x = 1\n" * 90_000)
    agent.try_edit("big.py")
    write(agent, "big.py", secret + "x = 1\n")
    assert "hardcoded-secret" not in additional(agent.edit("big.py"))


def test_a_brand_new_file_is_still_seen_at_stop(agent):
    agent.try_edit("fresh.py")
    write(agent, "fresh.py", STUB)
    agent.edit("fresh.py")
    agent.bash("python3 -m pytest -q", output="1 passed")
    assert "stub-body" in additional(agent.stop())


def test_a_slow_file_cant_stall_a_hook(agent):
    write(agent, "big.py", CLEAN)
    agent.try_edit("big.py")
    write(agent, "big.py", "x = 1\n" * 200_000)
    started = time.monotonic()
    agent.edit("big.py")
    assert time.monotonic() - started < 8


def test_an_audit_request_mentions_the_audit_skill(tmp_path):
    made = Agent(tmp_path)
    assert "occam-audit" in additional(made.prompt("audit this vibe coded app and fix what you find"))
    assert "occam-audit" not in additional(made.prompt("/occam:occam-audit audit this"))


def run_git(project, *args):
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


# ---------------------------------------------------------------- Codex


class Codex:
    def __init__(self, tmp_path):
        self.project = tmp_path / "project"
        self.project.mkdir()
        self.env = {**os.environ, "PLUGIN_DATA": str(tmp_path / "data"), "PLUGIN_ROOT": str(ROOT / "plugin")}

    def send(self, handler, **fields):
        event = {"session_id": "s1", "cwd": str(self.project), **fields}
        done = subprocess.run([sys.executable, str(CODEX_HOOK), handler], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=30)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout) if done.stdout.strip() else None

    def git(self, *args):
        run_git(self.project, *args)


@pytest.fixture
def codex(tmp_path):
    made = Codex(tmp_path)
    made.git("init", "-q")
    (made.project / "app.py").write_text(CLEAN)
    made.git("add", "-A")
    made.git("commit", "-qm", "init")
    return made


PATCH = "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n"


def test_codex_post_tool_reads_the_patch_and_mentions_what_it_introduced(codex):
    (codex.project / "app.py").write_text(STUB)
    result = codex.send("post-tool", tool_name="apply_patch", tool_input={"command": PATCH}, tool_response="ok")
    assert "stub-body" in result["hookSpecificOutput"]["additionalContext"]
    assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_codex_new_file_counts_but_a_committed_finding_in_a_subfolder_doesnt(codex):
    (codex.project / "pkg").mkdir()
    (codex.project / "pkg" / "old.py").write_text(STUB)
    codex.git("add", "-A")
    codex.git("commit", "-qm", "old")
    work = codex.project / "pkg"
    event = {"cwd": str(work), "tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n*** Update File: old.py\n@@\n-x\n+y\n*** End Patch\n"}, "tool_response": "ok"}
    (work / "old.py").write_text(STUB + "\nX = 1\n")
    assert codex.send("post-tool", **event) is None


def test_codex_someone_elses_uncommitted_finding_isnt_blamed_on_this_edit(codex):
    (codex.project / "app.py").write_text(STUB)  # already uncommitted when this session arrives
    codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": PATCH})
    (codex.project / "app.py").write_text(STUB + "\nX = 1\n")
    assert codex.send("post-tool", tool_name="apply_patch", tool_input={"command": PATCH}, tool_response="ok") is None
    assert codex.send("stop", last_assistant_message="done", stop_hook_active=False) is None


def test_codex_outside_git_only_recorded_baselines_attribute(tmp_path):
    made = Codex(tmp_path)
    (made.project / "app.py").write_text(STUB)
    assert made.send("post-tool", tool_name="apply_patch", tool_input={"command": PATCH}, tool_response="ok") is None


def test_codex_holds_edits_on_an_audit_only_request(codex):
    codex.send("user-prompt", prompt="audit this repository")
    denied = codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": PATCH})
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    outside = codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": PATCH.replace("app.py", "../a.py")})
    assert outside["hookSpecificOutput"]["permissionDecision"] == "deny"
    shell = codex.send("pre-tool", tool_name="Bash", tool_input={"command": "sed -i '' s/a/b/ app.py"})
    assert shell["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert codex.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}) is None
    codex.send("user-prompt", prompt="go ahead and fix it")
    assert codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": PATCH}) is None


def test_codex_stop_blocks_once_with_a_reason(codex):
    (codex.project / "app.py").write_text(STUB)
    codex.send("post-tool", tool_name="apply_patch", tool_input={"command": PATCH}, tool_response="ok")
    blocked = codex.send("stop", last_assistant_message="done", stop_hook_active=False)
    assert blocked["decision"] == "block" and "stub-body" in blocked["reason"]
    assert codex.send("stop", last_assistant_message="done", stop_hook_active=True) is None


def test_codex_audit_stop_lists_what_is_still_raised(codex):
    (codex.project / "app.py").write_text('DEBUG = bool(os.environ.get("APP_DEBUG", False))\n')
    codex.send("user-prompt", prompt="audit this repo and fix what you can")
    codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": PATCH})
    codex.send("post-tool", tool_name="apply_patch", tool_input={"command": PATCH}, tool_response="ok")
    blocked = codex.send("stop", last_assistant_message="done", stop_hook_active=False)
    assert blocked["decision"] == "block" and "still raises" in blocked["reason"] and "env-flag-truthy" in blocked["reason"]


def test_codex_stop_is_silent_when_clean(codex):
    codex.send("post-tool", tool_name="apply_patch", tool_input={"command": PATCH}, tool_response="ok")
    assert codex.send("stop", last_assistant_message="done", stop_hook_active=False) is None


def test_codex_hook_config_is_valid_and_points_at_real_scripts():
    config = json.loads((ROOT / "plugin" / "hooks" / "codex-hooks.json").read_text())
    assert {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"} <= set(config["hooks"])
    for groups in config["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command" and "codex_hook.py" in hook["command"]
    manifest = json.loads((ROOT / "plugin" / ".codex-plugin" / "plugin.json").read_text())
    assert (ROOT / "plugin" / manifest["hooks"]).exists() and manifest["name"] == "occam"


# ---------------------------------------------------------------- what a repository's own .git can name


def name_a_fetch_program(project, route):
    """Set up what a repository delivered with its .git folder can: reading a missing object runs a program its config names."""
    marker = project.parent / "program-ran"
    program = f"touch '{marker}'; false #"
    routes = {"ssh": {"remote.origin.url": "ssh://example.invalid/x.git", "core.sshCommand": program},
              "ext": {"remote.origin.url": f"ext::sh -c touch% {marker}", "protocol.ext.allow": "always"},
              "file": {"remote.origin.url": str(project), "remote.origin.uploadpack": program, "protocol.file.allow": "always"},
              "helper": {"remote.origin.url": "none::x", "alias.remote-none": f"!touch '{marker}'"}}
    blob = subprocess.run(["git", "rev-parse", "HEAD:app.py"], cwd=project, capture_output=True, text=True, check=True).stdout.strip()
    (project / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
    settings = {"core.repositoryformatversion": "1", "extensions.partialClone": "origin", "remote.origin.promisor": "true", **routes[route]}
    for key, value in settings.items():
        run_git(project, "config", key, value)
    # Plain git has to run it, or these tests would pass without blocking anything.
    subprocess.run(["git", "show", "HEAD:./app.py"], cwd=project, capture_output=True)
    if not marker.exists():
        pytest.skip("this git doesn't fetch missing objects, so there is nothing to block")
    marker.unlink()
    return marker


@pytest.mark.parametrize("route", ["ssh", "ext", "file", "helper"])
def test_claude_hook_runs_no_program_the_repository_names(agent, route):
    (agent.project / "app.py").write_text(CLEAN)
    run_git(agent.project, "init", "-q")
    run_git(agent.project, "add", "-A")
    run_git(agent.project, "commit", "-qm", "init")
    marker = name_a_fetch_program(agent.project, route)
    agent.send("post-tool", tool_name="Bash", tool_input={"command": "touch app.py"})  # no baseline, so stop asks git
    agent.stop()
    assert not marker.exists()


def test_codex_read_only_holds_a_shell_write_only_when_it_could_lose_work(codex):
    codex.send("user-prompt", prompt="Review only, change nothing.")
    held = codex.send("pre-tool", tool_name="Bash", tool_input={"command": "sed -i s/a/b/ app.py"})
    assert held["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert codex.send("pre-tool", tool_name="Bash", tool_input={"command": "echo hi > new.txt"}) is None
    for command in ("{ cd sub; rm other.py; }", "rm my\\ file.py", 'F=new.txt; F=app.py; rm "$F"'):
        assert codex.send("pre-tool", tool_name="Bash", tool_input={"command": command})["hookSpecificOutput"]["permissionDecision"] == "deny", command


@pytest.mark.parametrize("route", ["ssh", "ext", "file", "helper"])
def test_codex_hook_runs_no_program_the_repository_names(codex, route):
    marker = name_a_fetch_program(codex.project, route)
    (codex.project / "app.py").write_text(STUB)
    codex.send("post-tool", tool_name="apply_patch", tool_input={"command": PATCH}, tool_response="ok")
    assert not marker.exists()
