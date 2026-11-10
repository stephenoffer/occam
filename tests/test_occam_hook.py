"""The enforcement hook, driven as a real subprocess through realistic event sequences."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "plugin" / "hooks" / "occam_hook.py"
CONFIG = ROOT / "plugin" / "hooks" / "hooks.json"


class Agent:
    """Plays one session: each method sends what Claude Code would send, and returns the hook's parsed output."""

    def __init__(self, tmp_path, python=sys.executable):
        self.project = tmp_path / "project"
        self.project.mkdir()
        self.env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"), "CLAUDE_PLUGIN_ROOT": str(ROOT / "plugin"),
                    "CLAUDE_PROJECT_DIR": str(self.project)}
        self.env.pop("OCCAM_HOOKS", None)
        self.python = python

    def send(self, handler, **fields):
        event = {"session_id": "s1", "cwd": str(self.project), **fields}
        done = subprocess.run([self.python, str(HOOK), handler], input=json.dumps(event), capture_output=True,
                              text=True, env=self.env, timeout=20)
        assert done.returncode == 0, done.stderr
        assert "failed open" not in done.stderr, done.stderr
        return json.loads(done.stdout) if done.stdout.strip() else None

    def prompt(self, text):
        return self.send("user-prompt", prompt=text)

    def path(self, name):
        return str(self.project / name)

    def try_edit(self, name="app.py", **extra):
        return self.send("pre-tool", tool_name="Edit", tool_input={"file_path": self.path(name)}, **extra)

    def edit(self, name="app.py"):
        return self.send("post-tool", tool_name="Edit", tool_input={"file_path": self.path(name)})

    def try_bash(self, command, **extra):
        return self.send("pre-tool", tool_name="Bash", tool_input={"command": command}, **extra)

    def bash(self, command, ok=True, output=""):
        if ok:
            return self.send("post-tool", tool_name="Bash", tool_input={"command": command}, tool_response={"stdout": output})
        return self.send("post-failure", tool_name="Bash", tool_input={"command": command}, error="Exit code 1")

    def load(self, skill="occam:occam"):
        return self.send("post-tool", tool_name="Skill", tool_input={"skill": skill})

    def read_reference(self, name):
        return self.send("post-tool", tool_name="Read",
                         tool_input={"file_path": str(ROOT / "plugin/skills/occam/references" / f"{name}.md")})

    def review(self):
        self.send("post-tool", tool_name="Agent", tool_input={"subagent_type": "occam:code-reviewer"})
        return self.send("subagent-stop", agent_id="a1", agent_type="occam:code-reviewer")

    def stop(self, message="Done.", **extra):
        return self.send("stop", last_assistant_message=message, **extra)


@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path)


def decision(output):
    return ((output or {}).get("hookSpecificOutput") or {}).get("permissionDecision")


def added(output):
    return ((output or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")


# ------------------------------------------------------------ configuration

def test_powershell_is_covered_alongside_bash():
    config = json.loads(CONFIG.read_text())["hooks"]
    for event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        assert "PowerShell" in config[event][0]["matcher"]


def test_every_handler_in_the_config_exists_and_paths_use_the_plugin_root():
    config = json.loads(CONFIG.read_text())["hooks"]
    source = HOOK.read_text()
    for groups in config.values():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["command"] == "python3"
                assert hook["args"][0] == "${CLAUDE_PLUGIN_ROOT}/hooks/occam_hook.py"
                assert f'"{hook["args"][1]}":' in source
                assert hook["timeout"] <= 10, "hooks run on every tool call, so they must stay bounded"


# ------------------------------------------------------------ the core skill gets loaded

def test_code_edit_is_held_until_the_skill_is_loaded(agent):
    agent.prompt("Fix the bug in auth.py")
    assert decision(agent.try_edit("auth.py")) == "deny"
    agent.load()
    assert decision(agent.try_edit("auth.py")) is None


def test_skill_loaded_without_plugin_prefix_also_counts(agent):
    agent.prompt("Fix it")
    agent.load("occam")
    assert decision(agent.try_edit()) is None


def test_language_skill_alone_does_not_satisfy_the_gate(agent):
    agent.prompt("Fix it")
    agent.load("occam:occam-python")
    assert decision(agent.try_edit("auth.py")) == "deny"


def test_typing_the_skill_name_counts(agent):
    agent.prompt("/occam:occam fix the bug")
    assert decision(agent.try_edit()) is None


def test_expansion_event_counts(agent):
    agent.prompt("fix the bug")
    agent.send("expansion", command_name="occam:occam")
    assert decision(agent.try_edit()) is None


def test_documentation_edits_are_not_held(agent):
    agent.prompt("Translate the readme")
    assert decision(agent.try_edit("README.md")) is None


def test_dependency_requirements_txt_counts_as_code_despite_its_suffix(agent):
    agent.prompt("bump a dependency")
    assert decision(agent.try_edit("requirements.txt")) == "deny"


def test_files_outside_the_project_are_not_held(agent, tmp_path):
    agent.prompt("Fix it")
    output = agent.send("pre-tool", tool_name="Write", tool_input={"file_path": str(tmp_path / "elsewhere.py")})
    assert decision(output) is None


def test_scratchpad_is_not_held(agent):
    agent.prompt("Fix it")
    scratch = agent.project / "scratch"
    output = agent.send("pre-tool", tool_name="Write", tool_input={"file_path": str(scratch / "x.py")}, scratchpad_dir=str(scratch))
    assert decision(output) is None


def test_subagents_answer_to_the_coordinator(agent):
    agent.prompt("Fix it")
    assert decision(agent.try_edit(agent_id="a1")) is None


def test_plan_mode_is_left_to_the_host(agent):
    agent.prompt("Fix it")
    assert decision(agent.try_edit(permission_mode="plan")) is None


def test_a_hold_gives_way_rather_than_wedging_the_session(agent):
    agent.prompt("Fix it")
    assert decision(agent.try_edit("auth.py")) == "deny"
    assert decision(agent.try_edit("auth.py")) == "deny"
    output = agent.try_edit("auth.py")
    assert decision(output) is None
    assert "worth stating in the final report" in added(output)
    assert "retry" not in added(output), "the edit has already been allowed, so it shouldn't say to retry"


def test_parallel_edits_do_not_use_up_each_others_holds(agent):
    agent.prompt("Fix it")
    for name in ("auth.py", "payments.py", "tokens.py"):
        assert decision(agent.try_edit(name)) == "deny", "three edits in one response must all wait"


# ------------------------------------------------------------ read-only requests

@pytest.mark.parametrize("prompt", [
    "Review only, please don't change anything, I'll handle any fixes myself.",
    "Please review billing/invoice.py. Don't change anything, I just want your findings.",
    "How would you add caching? Planning only for now, no code changes.",
    "Audit-only pass please",
    "do not modify any files",
    "Look at this without changing the code.",
])
def test_read_only_requests_hold_edits(agent, prompt):
    assert "held for this turn" in added(agent.prompt(prompt))
    agent.load()
    assert decision(agent.try_edit()) == "deny"
    (agent.project / "app.py").write_text("a = 1\n")
    assert decision(agent.try_bash("sed -i '' s/a/b/ app.py")) == "deny"


@pytest.mark.parametrize("command", [
    "sed -i '' s/a/b/ app.py", "echo hi > app.py", "echo hi >> app.py", "rm app.py", "mv app.py b.py", "tee app.py < x",
    "cd sub && sed -i '' s/a/b/ other.py",  # a path can't be checked after a cd
    "sed -i '' s/a/b/ *.py",  # or when it's a pattern
    "python3 - <<'EOF'\nopen(sys.argv[1], 'w').write('x')\nEOF",  # or when it can't be read at all
    "python3 - <<'EOF'\nopen('app.py', 'w').write('x')\nEOF",
    # What each of these writes isn't what the path says, so a path that isn't there proves nothing.
    "if [ -d sub ]; then cd sub; fi; rm other.py", "{ cd sub; rm other.py; }", "for d in sub; do cd $d; rm other.py; done",
    "if cd sub; then rm other.py; fi", "if true; then rm app.py; fi", "for f in a; do rm app.py; done", "popd; rm other.py", "pushd sub && rm other.py", "builtin cd sub; rm other.py",
    "Set-Location sub; rm other.py", "env -C sub rm other.py", "rm my\\ file.py", 'rm "my file".py', "rm a'p'p.py",
    'F=new.txt; F=app.py; rm "$F"', "ln -s app.py new.txt && echo x > new.txt", "echo x > new.txt; cd sub",
    "cd .. && rm project/app.py", "cd $d; rm other.py", "cd /tmp; cd -; rm app.py", "cd /tmp && cd - && rm other.py",
])
def test_a_shell_command_that_could_lose_work_is_held_on_a_read_only_turn(agent, command):
    (agent.project / "app.py").write_text("a = 1\n")
    agent.prompt("Review only, change nothing.")
    assert decision(agent.try_bash(command)) == "deny"


@pytest.mark.parametrize("command", ["echo hi > new.txt", "touch new.txt", "cp app.py new.txt", "tee new.txt < app.py"])
def test_a_clearly_new_file_from_the_shell_is_not_held_on_a_read_only_turn(agent, command):
    (agent.project / "app.py").write_text("a = 1\n")
    agent.prompt("Review only, change nothing.")
    assert decision(agent.try_bash(command)) is None


def test_a_dangling_link_counts_as_already_there_on_a_read_only_turn(agent):
    (agent.project / "link.txt").symlink_to("somewhere-else.txt")
    agent.prompt("Review only, change nothing.")
    assert decision(agent.try_bash("echo hi > link.txt")) == "deny"


def test_a_shell_path_is_read_from_the_directory_the_command_runs_in(agent):
    (agent.project / "sub").mkdir()
    (agent.project / "sub" / "other.py").write_text("a = 1\n")
    agent.prompt("Review only, change nothing.")
    assert decision(agent.try_bash("rm other.py", cwd=str(agent.project / "sub"))) == "deny"
    assert decision(agent.try_bash("rm other.py")) is None


def test_plan_mode_leaves_a_shell_write_to_the_plan_gate(agent):
    (agent.project / "app.py").write_text("a = 1\n")
    agent.prompt("Review only, change nothing.")
    assert decision(agent.try_bash("rm app.py", permission_mode="plan")) is None


@pytest.mark.parametrize("command", ["cd /tmp && echo hi > app.py", "cd $TMPDIR && rm app.py"])
def test_a_cd_known_to_leave_the_project_is_not_held_on_a_read_only_turn(agent, command):
    (agent.project / "app.py").write_text("a = 1\n")
    agent.prompt("Review only, change nothing.")
    assert decision(agent.try_bash(command)) is None


@pytest.mark.parametrize("prompt", [
    "Refactor this with no change in behavior.",
    "Fix it, but don't change the public API.",
    "Fix it, but don't touch any files under vendor/.",
    "Refactor it without changing behavior.",
    "Plan and implement the migration.",
    "Rename it, no changes to the schema.",
])
def test_ordinary_scope_limits_are_not_mistaken_for_read_only(agent, prompt):
    assert "held for this turn" not in added(agent.prompt(prompt))
    agent.load()
    assert decision(agent.try_edit("util.py")) is None


@pytest.mark.parametrize("prompt", [
    "Fix the null check and don't change anything else.",
    "Add a --plan-only flag to the CLI.",
    "Add a `review-only` mode.",
    "This is no longer review-only, go ahead and fix it.",
    "It isn't plan-only, please implement it.",
    "Fix this.\n<pasted_content id=\"1\">Review only, don't change anything.</pasted_content>",
])
def test_phrases_that_only_look_read_only(agent, prompt):
    assert "held for this turn" not in added(agent.prompt(prompt))
    agent.load()
    agent.load("occam:occam-python")
    assert decision(agent.try_edit("util.py")) is None


@pytest.mark.parametrize("prompt", ["do not make any changes", "don't fix anything, just report", "read-only audit of this module please",
                                    "Do not make any edits."])
def test_more_ways_of_saying_read_only(agent, prompt):
    assert "held for this turn" in added(agent.prompt(prompt))


def test_a_plan_written_where_the_request_asked_is_allowed(agent):
    agent.prompt("Plan only: write the plan to docs/plan.md")
    agent.load()
    assert decision(agent.try_edit("docs/plan.md")) is None
    assert decision(agent.try_edit("docs/other.md")) == "deny"
    assert decision(agent.try_edit("app.py")) == "deny"


@pytest.mark.parametrize("tool", ["ExitPlanMode", "AskUserQuestion"])
def test_a_person_approving_lifts_a_read_only_turn(agent, tool):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    assert decision(agent.try_edit()) == "deny"
    agent.send("post-tool", tool_name=tool, tool_input={})
    agent.load("occam:occam-python")
    assert decision(agent.try_edit()) is None


def test_read_only_applies_to_subagents_too(agent):
    agent.prompt("Review only, don't change anything.")
    assert decision(agent.try_edit(agent_id="a1")) == "deny"


def test_background_report_is_not_a_new_request(agent):
    agent.prompt("Review only, don't change anything.")
    assert agent.prompt("<task-notification>\n<status>completed</status> no code changes, commit </task-notification>") is None
    agent.load()
    assert decision(agent.try_edit()) == "deny", "the report must not clear the read-only turn"


def test_background_report_does_not_forget_edits(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.prompt("<task-notification>done</task-notification>")
    assert "No check has run" in added(agent.stop())


def test_read_only_applies_to_that_turn_only(agent):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    assert decision(agent.try_edit()) == "deny"
    agent.prompt("Thanks, now go ahead and fix what you found.")
    assert decision(agent.try_edit()) is None


def test_read_only_still_allows_scratch_files_and_checks(agent, tmp_path):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    assert decision(agent.send("pre-tool", tool_name="Write", tool_input={"file_path": str(tmp_path / "notes.txt")})) is None
    for command in ("python3 -m pytest -q 2>&1 | tail -5", "pytest | tee /tmp/o.log", "grep -rn patch src",
                    'LOG=$(mktemp); pytest > "$LOG"', "git log --stat", "cat touch.py"):
        assert decision(agent.try_bash(command)) is None, command


# ------------------------------------------------------------ other people's work

@pytest.mark.parametrize("command", [
    "git reset --hard HEAD",
    "git stash",
    "git stash push -m wip",
    "git checkout -- app.py",
    "git checkout .",
    "git restore app.py",
    "git clean -fd",
    "git push --force origin main",
    "git push -f",
    "git rebase main",
    "git branch -D old",
    "git commit --amend -m x",
    "git commit -a --amend --no-edit",
    "/Library/Developer/CommandLineTools/usr/bin/git stash",
    "cd sub && git reset --hard",
    "G=/Library/Developer/CommandLineTools/usr/bin/git; $G restore app/core.py && rm app/extra.py",
    "G=/usr/bin/git; ${G} reset --hard",
    "bash -c 'git reset --hard'",
    'sh -c "git clean -fd"',
])
def test_destructive_git_asks_a_person(agent, command):
    agent.prompt("Fix the bug")
    assert decision(agent.try_bash(command)) == "ask"


@pytest.mark.parametrize("command", [
    "git status", "git diff HEAD", "git log --oneline", "git stash list", "git stash show", "git restore --staged a.py",
    "git add app.py", "git add -A", "git add .", "git commit -am wip", "git -c user.name=a commit -m x", "git checkout -b feature", "git show HEAD", "git branch -a", "git push origin main",
])
def test_safe_git_is_not_interrupted(agent, command):
    agent.prompt("Fix the bug")
    assert decision(agent.try_bash(command)) is None


@pytest.mark.parametrize("prompt", ["Fix the bug", "Fix it and commit the change", "Fix it. Do not commit anything."])
def test_committing_is_not_held_whatever_the_request_says_because_it_loses_nothing(agent, prompt):
    agent.prompt(prompt)
    assert decision(agent.try_bash("git commit -m fix")) is None
    assert decision(agent.try_bash("git add -A")) is None


@pytest.mark.parametrize("prompt,command", [
    ("Fix the password reset flow", "git reset --hard"),
    ("Clean up the parser", "git clean -fdx"),
    ("Please stash my work", "git stash"),
    ("Restore the old behavior", "git restore app.py"),
    ("Rebase is failing in CI, fix it", "git rebase main"),
])
def test_a_word_in_the_prompt_does_not_waive_a_data_losing_command(agent, prompt, command):
    agent.prompt(prompt)
    assert decision(agent.try_bash(command)) == "ask"


@pytest.mark.parametrize("command", ["git stash -u", "git stash --include-untracked", "git clean -d -f", "git --no-pager reset --hard",
                                     "git --git-dir=.git stash"])
def test_option_variations_are_still_caught(agent, command):
    agent.prompt("Fix the bug")
    assert decision(agent.try_bash(command)) == "ask"


def test_a_stash_stop_says_how_to_see_the_old_version(agent):
    # Two real runs reached for stash to compare old and new, which needs a person, and an unattended run has none.
    agent.prompt("Fix the bug")
    assert "git show HEAD:" in agent.try_bash("git stash push a.py -q")["hookSpecificOutput"]["permissionDecisionReason"]
    assert "git show HEAD:" not in agent.try_bash("git reset --hard")["hookSpecificOutput"]["permissionDecisionReason"]


# ------------------------------------------------------------ shell edits

@pytest.mark.parametrize("command", [
    "sed -i '' 's/a/b/' app.py",
    "cat > app.py <<'EOF'\nx = 1\nEOF",
    "cat >> tests/test_app.py <<'EOF'\ndef test_x(): pass\nEOF",
    "echo hi > app.py",
    "python3 - <<'EOF'\nopen('app.py', 'w').write('x')\nEOF",
    "python3 - <<'EOF'\nfrom pathlib import Path\nPath('a.py').write_text('x')\nEOF",
    "mv a.py b.py",
    "rm old.py",
    "python3 <<'EOF'\nopen('a.py', 'w').write('x')\nEOF",
    "cp template.py a.py",
    "sed -E -i '' 's/a/b/' app.py",
    "ruff check --fix .",
    "ruff format .",
    "black .",
    "npm install left-pad",
    "yarn add left-pad",
    "uv add requests",
    "mv app.py /tmp/",
    "tee app.py < x",
    "echo hi > \"my file.py\"",
    "bash -c 'echo hi > app.py'",
])
def test_shell_edits_are_not_held_before_the_skill_loads(agent, command):
    agent.prompt("Fix it")
    assert decision(agent.try_bash(command)) is None


@pytest.mark.parametrize("command", [
    "python3 -m pytest -q 2>&1 | tail -5",
    "python3 -c 'print(1 > 0)'",
    "ls -la > /dev/null",
    "python3 run.py > $TMPDIR/out.txt",
    "cat app.py",
    "grep -n 'a > b' app.py",
    "python3 - <<'EOF'\nif 2 > 1:\n    print('yes')\nEOF",
    "D=$TMPDIR/orig; mkdir -p $D; cp -R src $D/; rm -rf $TMPDIR/orig",
    "echo done 2>&1",
    "ruff check .",
    "npm install",
    "npm test",
    "pip install -r requirements.txt",
    "grep -rn 'tee' src",
    "cat notes.txt | tee /tmp/copy.txt",
    "ls > /tmp/listing.txt",
])
def test_reading_and_running_are_not_held(agent, command):
    agent.prompt("Fix it")
    assert decision(agent.try_bash(command)) is None


# ------------------------------------------------------------ references

def test_a_high_consequence_path_states_the_security_facts_instead_of_holding(agent):
    agent.prompt("Add an export")
    agent.load()
    output = agent.try_edit("billing/app.py")
    assert decision(output) is None and "idempotency key" in added(output)
    path = re.search(r"(/\S+security\.md)", added(output)).group(1)
    assert Path(path).exists(), "the hook must name a path that exists"
    assert "idempotency key" not in added(agent.try_edit("billing/app.py")), "once is enough"


def test_a_reference_already_read_isnt_repeated(agent):
    agent.prompt("Add an export")
    agent.load()
    agent.read_reference("security")
    assert "idempotency key" not in added(agent.try_edit("billing/app.py"))


def test_a_performance_request_states_the_performance_facts_instead_of_holding(agent):
    agent.prompt("It falls over at 1,000,000 records. Make it fit in memory.")
    agent.load()
    output = agent.try_edit("pipeline.py")
    assert decision(output) is None and "find the stage that binds" in added(output)
    assert "find the stage that binds" not in added(agent.try_edit("pipeline.py"))


@pytest.mark.parametrize("prompt", ["The report prints 1 items when a count is one.", "Only the first 100 contacts import.",
                                    "Show 25 rows per page."])
def test_small_numbers_are_not_a_workload(agent, prompt):
    agent.prompt(prompt)
    agent.load()
    agent.load("occam:occam-python")
    assert decision(agent.try_edit("report.py")) is None


@pytest.mark.parametrize("prompt", ["It dies on 1,000,000 records.", "We feed it 50000 urls.", "Handle 2M rows.", "p95 latency is 4s."])
def test_real_workloads_are(agent, prompt):
    agent.prompt(prompt)
    agent.load()
    assert "find the stage that binds" in added(agent.try_edit("report.py"))


def test_a_dependency_manifest_states_the_design_facts_instead_of_holding(agent):
    agent.prompt("Add requests to the project")
    agent.load()
    output = agent.try_edit("pyproject.toml")
    assert decision(output) is None and "the package the documentation means" in added(output)
    assert "the package the documentation means" not in added(agent.try_edit("pyproject.toml"))


def test_reading_a_reference_through_the_shell_counts(agent):
    agent.prompt("Add an export")
    agent.load()
    agent.load("occam:occam-python")
    agent.bash("cat " + str(ROOT / "plugin/skills/occam/references/security.md"))
    assert decision(agent.try_edit("billing/app.py")) is None


def test_shell_edit_of_a_high_consequence_file_is_not_held_for_the_reference(agent):
    agent.prompt("Tidy this")
    agent.load()
    assert decision(agent.try_bash("sed -i '' s/a/b/ auth/login.py")) is None


def test_shell_edit_of_a_high_consequence_file_needs_the_reviewer(agent):
    agent.prompt("Tidy this")
    agent.load()
    agent.read_reference("security")
    agent.bash("sed -i '' s/a/b/ auth/login.py")
    agent.bash("pytest", output="1 passed")
    assert "occam:code-reviewer" in added(agent.stop("1 passed"))


def test_ordinary_edit_needs_no_reference(agent):
    agent.prompt("Fix the wording in the report")
    agent.load()
    assert decision(agent.try_edit("report.py")) is None


# ------------------------------------------------------------ optional skills are offered, not forced

def test_routine_edit_only_mentions_the_language_skill_once(agent):
    agent.prompt("Fix the wording")
    agent.load()
    first = agent.try_edit("a.py")
    assert decision(first) is None and "occam-python" in added(first)
    assert "occam-python" not in added(agent.try_edit("b.py"))


def test_a_risky_request_mentions_the_language_skill_once_and_holds_nothing(agent):
    agent.prompt("Cancellation gets swallowed in fetcher.py, please fix it")
    agent.load()
    first = agent.try_edit("fetcher.py")
    assert decision(first) is None and "/occam-python/SKILL.md" in added(first)
    assert "/occam-python/SKILL.md" not in added(agent.try_edit("fetcher.py"))


def test_risky_edit_content_mentions_the_skill_too(agent):
    agent.prompt("Tidy this up")
    agent.load()
    output = agent.send("pre-tool", tool_name="Edit", tool_input={"file_path": agent.path("a.js"), "new_string": "const n = limit ?? 0;"})
    assert decision(output) is None and "/occam-typescript/SKILL.md" in added(output)


def test_loaded_language_skill_means_no_pause(agent):
    agent.prompt("Cancellation gets swallowed, please fix it")
    agent.load()
    agent.load("occam:occam-python")
    assert decision(agent.try_edit("fetcher.py")) is None


def test_each_language_is_mentioned_once(agent):
    agent.prompt("Cancellation gets swallowed, please fix it")
    agent.load()
    assert "/occam-python/SKILL.md" in added(agent.try_edit("a.py"))
    assert "/occam-go/SKILL.md" in added(agent.try_edit("a.go")), "each language gets its own mention"
    assert "/occam-python/SKILL.md" not in added(agent.try_edit("b.py"))


def test_language_skill_not_mentioned_once_loaded(agent):
    agent.prompt("Fix the wording")
    agent.load()
    agent.load("occam:occam-python")
    assert "occam-python" not in added(agent.try_edit("a.py"))


@pytest.mark.parametrize("name,skill", [("a.ts", "occam-typescript"), ("a.rs", "occam-rust"), ("a.go", "occam-go"),
                                        ("A.kt", "occam-jvm"), ("a.cpp", "occam-cpp"), ("a.sql", "occam-sql"), ("a.sh", "occam-shell")])
def test_each_language_maps_to_a_real_skill(agent, name, skill):
    agent.prompt("Fix the wording")
    agent.load()
    output = agent.try_edit(name)
    assert skill in added(output) or skill in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert (ROOT / "plugin" / "skills" / skill / "SKILL.md").exists()


def test_overwriting_a_substantial_file_mentions_comparing_old_and_new_once(agent):
    agent.prompt("Tidy this")
    agent.load()
    agent.load("occam:occam-python")
    (agent.project / "engine.py").write_text("x = 1\n" * 40)
    first = agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path("engine.py"), "content": "y = 1\n"})
    assert decision(first) is None, "this informs, it doesn't hold"
    assert "comparing old and new" in added(first)
    second = agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path("engine.py"), "content": "z = 1\n"})
    assert "comparing old and new" not in added(second)


def test_a_large_edit_mentions_it_too(agent):
    agent.prompt("Tidy this")
    agent.load()
    agent.load("occam:occam-python")
    output = agent.send("pre-tool", tool_name="Edit", tool_input={"file_path": agent.path("engine.py"), "old_string": "line\n" * 40, "new_string": "y"})
    assert "comparing old and new" in added(output)


@pytest.mark.parametrize("name,lines", [("small.py", 5), ("notes.md", 80), ("new.py", 0)])
def test_small_docs_and_new_files_are_not_rewrites(agent, name, lines):
    agent.prompt("Tidy this")
    agent.load()
    agent.load("occam:occam-python")
    if lines:
        (agent.project / name).write_text("x\n" * lines)
    output = agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path(name), "content": "y\n"})
    assert "comparing old and new" not in added(output)


def test_verification_guidance_mentioned_on_first_test_edit(agent):
    agent.prompt("Add a test")
    agent.load()
    assert "verification.md" in added(agent.try_edit("tests/test_a.py"))
    assert "verification.md" not in added(agent.try_edit("tests/test_b.py"))


def test_collaboration_guidance_mentioned_on_first_delegation(agent):
    agent.prompt("Fix it")
    agent.load()
    first = agent.send("pre-tool", tool_name="Agent", tool_input={"subagent_type": "general-purpose"})
    assert "collaboration.md" in added(first)
    assert agent.send("pre-tool", tool_name="Agent", tool_input={"subagent_type": "general-purpose"}) is None


# ------------------------------------------------------------ session and prompt context

def test_session_start_waits_and_compaction_offers_reload(agent):
    """The rule card waits for the first tool call (the user's decision of 2026-11-08), so a plain start says nothing here."""
    assert "occam:occam" not in added(agent.send("session-start", source="startup"))
    assert "compacted" in added(agent.send("session-start", source="compact"))


def test_review_request_mentions_the_skill_until_it_is_loaded(agent):
    assert "occam:occam" in added(agent.prompt("Can you review this pull request?"))
    agent.load()
    assert agent.prompt("Can you review this other pull request?") is None


def test_unrelated_prompt_adds_nothing(agent):
    assert agent.prompt("what's the difference between a mutex and a semaphore?") is None


# ------------------------------------------------------------ stop

def finish_edit(agent, name="app.py"):
    agent.load()
    agent.try_edit(name)
    agent.edit(name)


def test_stop_without_edits_is_silent(agent):
    agent.prompt("Explain this code")
    assert agent.stop() is None


def test_edit_without_a_check_sends_the_agent_back(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    assert "No check has run" in added(agent.stop())


def test_check_after_the_edit_lets_it_finish(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash("python3 -m pytest -q", output="3 passed")
    assert agent.stop("Fixed. 3 passed.") is None


@pytest.mark.parametrize("command", ["pip install pytest", "python3 --version", "python3 -m pip install x", "npm install",
                                     "echo pytest", "cat test_app.py", "ls tests"])
def test_these_are_not_checks(agent, command):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash(command)
    assert "No check has run" in added(agent.stop())


@pytest.mark.parametrize("command", ["npx jest", "npm test", "npm run lint", "yarn test", "cargo test", "go vet ./...", "make test",
                                     "uv run pytest", "node --test", "node app.js", "./gradlew test", "bash scripts/check.sh",
                                     "python3 -m stockreport x.csv", "python3 -c 'import app'", "FOO=1 pytest -q"])
def test_these_are_checks(agent, command):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash(command)
    assert agent.stop() is None


def test_a_check_launched_in_the_background_has_not_run(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.send("post-tool", tool_name="Bash", tool_input={"command": "pytest", "run_in_background": True}, tool_response={})
    assert "No check has run" in added(agent.stop())


def test_exact_changed_files_are_used_when_the_host_reports_them(agent):
    agent.prompt("Tidy this")
    agent.load()
    agent.read_reference("security")
    agent.send("post-tool", tool_name="Bash", tool_input={"command": "./my-refactor-tool"},
               tool_response={"bashEditDiff": {"changedFiles": [agent.path("auth/login.py")]}})
    assert "login.py" in added(agent.stop())


def test_subagent_edits_count_toward_stop(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.send("post-tool", tool_name="Edit", tool_input={"file_path": agent.path("a.py")}, agent_id="a1")
    assert "No check has run" in added(agent.stop())


def test_real_entry_point_counts_as_a_check(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash("python3 -m stockreport data/sample.csv")
    assert agent.stop() is None


def test_check_before_the_last_edit_does_not_count(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash("pytest", output="1 passed")
    agent.edit("app.py")
    assert "No check has run" in added(agent.stop())


def test_failing_check_still_counts_as_having_run(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash("pytest", ok=False)
    assert agent.stop("One test still fails, which predates this change.") is None


def test_docs_only_change_needs_no_check(agent):
    agent.prompt("Update the readme")
    agent.edit("README.md")
    assert agent.stop() is None


def test_shell_edit_counts_as_an_edit(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.bash("sed -i '' s/a/b/ app.py")
    assert "No check has run" in added(agent.stop())


def test_loop_guard(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    assert "No check has run" in added(agent.stop())
    assert agent.stop(stop_hook_active=True) is None


def test_subagent_and_background_work_are_left_alone(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    assert agent.stop(agent_id="a1") is None
    assert agent.stop(background_tasks=[{"id": "1", "type": "subagent"}]) is None


def test_a_background_dev_server_does_not_excuse_skipping_checks(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    assert "No check has run" in added(agent.stop(background_tasks=[{"id": "1", "type": "shell", "command": "npm run dev"}]))


def test_earlier_turns_do_not_count_against_this_one(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.stop()
    agent.prompt("Thanks. What does this function do?")
    assert agent.stop() is None


def test_claim_with_no_passing_run_is_caught(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash("python3 -m stockreport x.csv", ok=False)
    assert "no check passed" in added(agent.stop("All tests pass now."))


def test_negated_claim_is_not_a_claim(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash("pytest", ok=False)
    assert agent.stop("The tests did not pass, because the database is down.") is None


def test_zero_collected_is_not_a_passing_run(agent):
    agent.prompt("Fix it")
    finish_edit(agent)
    agent.bash("pytest", output="collected 0 items")
    assert "no check passed" in added(agent.stop("Tests pass."))


def test_high_consequence_change_needs_the_reviewer(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.read_reference("security")
    agent.edit("auth/login.py")
    agent.bash("pytest", output="1 passed")
    assert "occam:code-reviewer" in added(agent.stop("1 passed"))
    agent.review()
    assert agent.stop("1 passed") is None


def test_a_review_only_counts_once_finished_and_after_the_last_edit(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.read_reference("security")
    agent.edit("auth/login.py")
    agent.bash("pytest", output="1 passed")
    agent.send("post-tool", tool_name="Agent", tool_input={"subagent_type": "occam:code-reviewer"})
    assert "occam:code-reviewer" in added(agent.stop("1 passed")), "launched isn't finished"
    agent.send("subagent-stop", agent_id="a1", agent_type="occam:code-reviewer")
    assert agent.stop("1 passed") is None
    agent.edit("auth/login.py")
    agent.bash("pytest", output="1 passed")
    assert "occam:code-reviewer" in added(agent.stop("1 passed")), "the review predates the last edit"


def test_a_directory_above_the_project_cannot_make_files_high_consequence(tmp_path):
    outer = tmp_path / "payments-api"
    outer.mkdir()
    agent = Agent(outer)
    agent.prompt("Fix the wording")
    agent.load()
    agent.load("occam:occam-python")
    assert decision(agent.try_edit("report.py")) is None
    agent.edit("report.py")
    agent.bash("pytest", output="1 passed")
    assert agent.stop("1 passed") is None


def test_an_unread_diff_alone_doesnt_send_an_agent_back(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.edit("a.py")
    agent.edit("b.py")
    agent.bash("pytest", output="1 passed")
    assert agent.stop("1 passed") is None


def test_an_unread_diff_is_mentioned_when_sent_back_anyway(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.edit("a.py")
    agent.edit("b.py")
    said = added(agent.stop("Fixed."))
    assert "No check has run" in said
    assert "final diff hasn't been inspected" in said


def test_a_read_diff_isnt_mentioned(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.edit("a.py")
    agent.edit("b.py")
    agent.bash("git diff HEAD")
    assert "final diff" not in added(agent.stop("Fixed."))


def test_a_send_back_asks_for_the_whole_report_not_an_answer_to_the_note(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.edit("a.py")
    said = added(agent.stop("Fixed."))
    assert "write the whole report again" in said
    assert "without discussing the note" in said
    assert "no report until it's done" in said and "your next message is the report" in said


def test_all_problems_are_reported_at_once_because_stop_only_continues_once(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.edit("auth/a.py")
    agent.edit("b.py")
    reason = added(agent.stop("All tests pass."))
    assert "No check has run" in reason and "code-reviewer" in reason and "diff" in reason and "no check passed" in reason


# ------------------------------------------------------------ robustness

@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", "null"])
@pytest.mark.parametrize("handler", ["session-start", "user-prompt", "pre-tool", "post-tool", "post-failure", "stop", "expansion", "subagent-stop"])
def test_bad_input_never_blocks(tmp_path, handler, stdin):
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path)}
    done = subprocess.run([sys.executable, str(HOOK), handler], input=stdin, capture_output=True, text=True, env=env, timeout=20)
    assert done.returncode == 0
    if done.stdout.strip():  # the rule card says "blocked", so this reads the decision rather than the text
        output = json.loads(done.stdout)
        assert output.get("decision") != "block" and (output.get("hookSpecificOutput") or {}).get("permissionDecision") != "deny"


def test_unwritable_state_fails_open(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(blocker)}
    event = json.dumps({"session_id": "s", "tool_name": "Edit", "tool_input": {"file_path": "a.py"}, "cwd": str(tmp_path)})
    done = subprocess.run([sys.executable, str(HOOK), "pre-tool"], input=event, capture_output=True, text=True, env=env, timeout=20)
    assert done.returncode == 0 and done.stdout == ""
    assert "failed open" in done.stderr


def test_off_switch(agent):
    agent.env["OCCAM_HOOKS"] = "off"
    agent.prompt("Fix it")
    assert decision(agent.try_edit()) is None


def test_sessions_are_isolated(agent):
    agent.prompt("Fix it")
    agent.load()
    other = agent.send("pre-tool", tool_name="Edit", tool_input={"file_path": agent.path("auth.py")}, session_id="s2")
    assert decision(other) == "deny"


def test_hostile_session_id_stays_in_the_data_directory(agent, tmp_path):
    agent.send("user-prompt", prompt="x", session_id="../../../../evil")
    assert not (tmp_path.parent / "evil.jsonl").exists()
    assert list((tmp_path / "data" / "sessions").glob("*evil*"))


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="no system python")
def test_runs_on_the_stock_system_python(tmp_path):
    agent = Agent(tmp_path, python="/usr/bin/python3")
    agent.prompt("Fix it")
    assert decision(agent.try_edit("auth.py")) == "deny"
    agent.load()
    agent.edit("auth.py")
    assert "No check has run" in added(agent.stop())
