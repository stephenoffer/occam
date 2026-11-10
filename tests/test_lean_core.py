"""The rule card, the guard level, the self-review default and the subagent card, taken from Ponytail and Superpowers on 2026-11-06.

None of this is measured on an agent. These pin what the hooks say and hold, through the real hook script.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

import rule_card  # noqa: E402
import stop_checks  # noqa: E402
from classify import ASKS_FOR_REVIEW  # noqa: E402

HOOK = ROOT / "plugin" / "hooks" / "occam_hook.py"


class Session:
    def __init__(self, tmp_path, level=None):
        self.project = tmp_path / "project"
        self.project.mkdir()
        self.env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"), "CLAUDE_PLUGIN_ROOT": str(ROOT / "plugin"),
                    "CLAUDE_PROJECT_DIR": str(self.project), "OCCAM_STATE_DIR": str(tmp_path / "state")}
        self.env.pop("OCCAM_HOOKS", None)
        if level:
            self.env["OCCAM_HOOKS"] = level

    def send(self, handler, **fields):
        event = {"session_id": "s1", "cwd": str(self.project), **fields}
        done = subprocess.run([sys.executable, str(HOOK), handler], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        assert done.returncode == 0 and "failed open" not in done.stderr, done.stderr
        return json.loads(done.stdout) if done.stdout.strip() else {}

    def edit(self, name, old, new):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(old + "\n")
        return {"tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}

    def do(self, event):
        before = self.send("pre-tool", **event)
        assert decision(before) != "deny", before
        tool = event["tool_input"]
        path = Path(tool["file_path"])
        path.write_text(path.read_text().replace(tool["old_string"], tool["new_string"]))
        return before, self.send("post-tool", **event)

    def check(self, command="python -m pytest -q", output="3 passed"):
        event = {"tool_name": "Bash", "tool_input": {"command": command}}
        self.send("pre-tool", **event)
        return self.send("post-tool", **event, tool_response={"stdout": output})


def spec(output):
    return (output or {}).get("hookSpecificOutput") or {}


def decision(output):
    return spec(output).get("permissionDecision")


def said(output):
    return spec(output).get("additionalContext", "")


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


@pytest.fixture
def guarded(tmp_path):
    return Session(tmp_path, level="guard")


ORDINARY = "\n".join(f"row_{i} = format_row({i})" for i in range(25))  # past the old small-edit size, with nothing consequential in it


# ---------------------------------------------------------------- the rule card


def test_the_card_comes_with_the_first_tool_call_not_at_session_start(session):
    """Moved from session start by the user on 2026-11-08: a session that loads the core first hears these rules there at length."""
    assert rule_card.RULES not in said(session.send("session-start", source="startup"))
    session.send("user-prompt", prompt="fix it")
    first = said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))
    assert rule_card.RULES in first and "load the full `occam:occam` skill before editing" in first
    assert rule_card.RULES not in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))


def test_a_session_that_loads_the_core_first_never_hears_the_card(session):
    session.send("user-prompt", prompt="fix it")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"}, tool_response={})
    assert rule_card.RULES not in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))
    before, _ = session.do(session.edit("app.py", "x = 1", "x = 2"))
    assert rule_card.RULES not in said(before)


def test_a_first_read_hears_the_card_after_it(session):
    """A Read's pre-tool hook skips the session record to stay fast, so the card comes with its result."""
    session.send("user-prompt", prompt="what does app.py do?")
    path = session.project / "app.py"
    path.write_text("x = 1\n")
    event = {"tool_name": "Read", "tool_input": {"file_path": str(path)}}
    assert rule_card.RULES not in said(session.send("pre-tool", **event))
    assert rule_card.RULES in said(session.send("post-tool", **event, tool_response={}))
    assert rule_card.RULES not in said(session.send("post-tool", **event, tool_response={}))


def test_a_held_first_call_leaves_the_card_for_the_next(session):
    session.send("user-prompt", prompt="fix it")
    held = session.send("pre-tool", **session.edit("auth.py", "x = 1", "x = 2"))
    assert decision(held) == "deny" and rule_card.RULES not in json.dumps(held)
    assert rule_card.RULES in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))


def test_a_clear_starts_the_card_again_and_compaction_gives_it_at_once(session):
    session.send("user-prompt", prompt="fix it")
    session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"})
    session.send("session-start", source="clear")
    assert rule_card.RULES in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))
    assert rule_card.RULES in said(session.send("session-start", source="compact"))
    assert rule_card.RULES not in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))


def test_a_subagents_tool_calls_dont_get_the_main_card(session):
    session.send("user-prompt", prompt="fix it")
    assert rule_card.RULES not in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}, agent_id="a1"))
    assert rule_card.RULES in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))


def test_compaction_gives_the_card_again_with_the_reload_note(session):
    text = said(session.send("session-start", source="compact"))
    assert rule_card.RULES in text and "Loading `occam:occam` again restores it" in text


def test_an_ordinary_edit_past_the_old_small_size_goes_ahead_under_the_card(session):
    session.send("session-start", source="startup")
    session.send("user-prompt", prompt="fix it")
    before, _ = session.do(session.edit("app.py", "x = 1", ORDINARY))
    assert decision(before) is None
    assert rule_card.RULES in said(before), "the first tool call carries the card"


def test_a_session_that_never_heard_the_card_hears_it_once_before_its_first_edit(session):
    session.send("user-prompt", prompt="fix it")
    first, _ = session.do(session.edit("app.py", "x = 1", "x = 2"))
    second, _ = session.do(session.edit("app.py", "x = 2", "x = 3"))
    assert rule_card.RULES in said(first) and rule_card.RULES not in said(second)


@pytest.mark.parametrize("prompt, name, old, new", [
    ("fix it", "auth.py", "x = 1", "x = 2"),
    ("fix it", "billing/invoice.py", "x = 1", "x = 2"),
    ("fix the authorization check", "app.py", "x = 1", "x = 2"),
    ("fix it", "app.py", "x = 1", "password = read_password()"),
])
def test_consequential_edits_still_wait_for_the_skill(session, prompt, name, old, new):
    session.send("session-start", source="startup")
    session.send("user-prompt", prompt=prompt)
    output = session.send("pre-tool", **session.edit(name, old, new))
    assert decision(output) == "deny" and "has not been loaded" in spec(output)["permissionDecisionReason"]


def test_a_loaded_skill_lifts_the_hold(session):
    session.send("user-prompt", prompt="fix it")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    assert decision(session.send("pre-tool", **session.edit("auth.py", "x = 1", "x = 2"))) is None


# ---------------------------------------------------------------- subagents


@pytest.mark.parametrize("agent_type", ["general-purpose", "Explore", "my-plugin:writer", "feature-dev:code-reviewer", "x:auditor"])
def test_a_subagent_hears_the_rules(session, agent_type):
    output = session.send("subagent-start", agent_type=agent_type, agent_id="a1")
    assert spec(output).get("hookEventName") == "SubagentStart" and rule_card.RULES in said(output)


@pytest.mark.parametrize("agent_type", ["occam:code-reviewer", "code-reviewer", "occam:auditor"])
def test_occams_own_agents_carry_their_own_briefs(session, agent_type):
    assert session.send("subagent-start", agent_type=agent_type, agent_id="a1") == {}


# ---------------------------------------------------------------- reviewing high-consequence work


def test_migrations_and_webhooks_get_a_self_review_note(session):
    session.send("user-prompt", prompt="fix the total")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    _, after = session.do(session.edit("migrations/0042_totals.py", "x = 1", "x = 2"))
    assert "review the whole diff yourself" in said(after) and "code-reviewer" not in said(after)


def test_stop_asks_for_a_stated_self_review_and_accepts_one(session):
    session.send("user-prompt", prompt="fix the total")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    session.do(session.edit("migrations/0042_totals.py", "x = 1", "x = 2"))
    session.check()
    assert "Self-review:" in said(session.send("stop", last_assistant_message="Fixed the total. 3 tests pass. I self-reviewed the whole diff."))
    accepted = said(session.send("stop", last_assistant_message="Fixed the total, 3 tests pass.\n\nSelf-review: no issues found; callers and retries are fine."))
    assert "reviewed" not in accepted and "code-reviewer" not in accepted


def test_saying_it_was_not_reviewed_is_not_a_self_review(session):
    session.send("user-prompt", prompt="fix the total")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    session.do(session.edit("migrations/0042_totals.py", "x = 1", "x = 2"))
    session.check()
    assert "doesn't say the diff was reviewed" in said(session.send("stop", last_assistant_message="Fixed.\nSelf-review: not done."))


@pytest.mark.parametrize("message", ["Self-review: no issues found in the whole diff.", "**Self-review:** read every caller and the retry path.",
                                     "- Self-review: checked callers, invariants and empty input.", "> Self-review: the rounding is now done once.",
                                     "Self-review: none found, callers and retries fine.", "Fixed; 3 passed. Self-review: callers fine.", "1. Self-review: callers fine",
                                     "- **Self-review** \u2014 callers fine", "| Self-review | read callers |", "**Self-review:**\n- callers fine\n- retries fine"])
def test_a_self_review_line_counts(message):
    assert stop_checks.says_it_self_reviewed("Fixed the total.\n" + message)


@pytest.mark.parametrize("message", ["Self-review: not done.", "Self-review: pending", "Self-review: none", "Self-review: \u2014", "Self-review: didn't get to it",
                                     "Self-review: can't, out of time", "I self-reviewed the diff.", "I didn't get a chance to do a proper self-review.",
                                     "No issues found in my self-review of the whole diff.", "I recommend a self-review.",
                                     "Self-review:\n- skipped, out of time", "**Self-review:**\n- not done", "Self-review:\nChecks: 3 passed", "Self-review: no.",
                                     "Self-review: I didn't get to it.", "Self-review: (not done)", "Self-review: still to do", "Self-review: deferred to you",
                                     "Self-review: \u2717", "Self-review: false"])
def test_anything_else_is_not_a_self_review_line(message):
    assert not stop_checks.says_it_self_reviewed("Fixed the total.\n" + message)


@pytest.mark.parametrize("prompt", ["fix the total and get the changes reviewed", "have the code reviewer check it", "have a reviewer look at it",
                                    "I want it independently reviewed", "get a code review", "review it with a subagent", "get a second opinion on this"])
def test_requests_for_a_review(prompt):
    assert ASKS_FOR_REVIEW.search(prompt)


@pytest.mark.parametrize("prompt", ["fix the total", "add pagination to the invoice list", "the rounding is off by a cent"])
def test_ordinary_requests_are_not_requests_for_a_review(prompt):
    assert not ASKS_FOR_REVIEW.search(prompt)


def test_a_pasted_mention_of_a_review_is_not_a_request(session):
    assert not stop_checks.asks_for_a_review('fix the total <pasted_content>get a code review</pasted_content>')


def test_the_note_changes_when_a_later_edit_needs_the_reviewer(session):
    session.send("user-prompt", prompt="fix the total and the session timeout")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    _, first = session.do(session.edit("migrations/0042_totals.py", "x = 1", "x = 2"))
    _, second = session.do(session.edit("users/session.py", "x = 1", "x = 2"))
    assert "review the whole diff yourself" in said(first)
    assert "session.py is security-critical" in said(second) and "`occam:code-reviewer` reviews this" in said(second)


def test_the_note_says_why_when_the_request_asks(session):
    session.send("user-prompt", prompt="fix the migration and get it reviewed")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    _, after = session.do(session.edit("migrations/0042_totals.py", "x = 1", "x = 2"))
    assert "the request asks for a review" in said(after) and "security-critical" not in said(after)


@pytest.mark.parametrize("prompt, name", [("fix the login", "app/auth.py"), ("fix the total", "billing/invoice.py"), ("fix the refund", "payments/refunds.py"),
                                          ("fix the migration and get it reviewed", "migrations/0042_totals.py")])
def test_security_money_or_a_request_still_get_the_fresh_reviewer(session, prompt, name):
    session.send("user-prompt", prompt=prompt)
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    _, after = session.do(session.edit(name, "x = 1", "x = 2"))
    assert "`occam:code-reviewer` reviews this" in said(after)
    session.check()
    assert "hasn't finished a review" in said(session.send("stop", last_assistant_message="Fixed, 3 tests pass.\nSelf-review: no issues."))


def test_a_write_over_a_file_too_large_to_read_is_held_from_a_subfolder(session):
    package = session.project / "pkg"
    package.mkdir()
    (package / "table.py").write_text("row = 1\n" * 400_000)
    session.send("user-prompt", prompt="fix it")
    event = {"tool_name": "Write", "tool_input": {"file_path": str(package / "table.py"), "content": "row = 2\n"}}
    output = session.send("pre-tool", cwd=str(package), **event)
    assert decision(output) == "deny" and "has not been loaded" in spec(output)["permissionDecisionReason"]


def test_the_note_says_a_money_change_is_why(session):
    session.send("user-prompt", prompt="fix the total")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    _, after = session.do(session.edit("billing/invoice.py", "x = 1", "x = 2"))
    assert "invoice.py handles money" in said(after) and "`occam:code-reviewer` reviews this" in said(after)


# ---------------------------------------------------------------- the guard level


def test_guard_says_nothing_at_session_start_or_to_a_subagent(guarded):
    assert guarded.send("session-start", source="startup") == {}
    assert guarded.send("subagent-start", agent_type="general-purpose", agent_id="a1") == {}
    guarded.send("user-prompt", prompt="fix it")
    assert guarded.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}) == {}, "no card at the first tool call either"


def test_guard_holds_no_edit_for_the_skill_and_adds_no_notes(guarded):
    guarded.send("user-prompt", prompt="fix the authorization check")
    before, after = guarded.do(guarded.edit("auth.py", "x = 1", "x = 2"))
    assert before == {} and after == {}


def test_guard_still_asks_before_work_is_thrown_away(guarded):
    guarded.send("user-prompt", prompt="clean this up")
    assert decision(guarded.send("pre-tool", tool_name="Bash", tool_input={"command": "git stash push -u"})) == "ask"


def test_guard_still_holds_edits_on_a_read_only_request(guarded):
    guarded.send("user-prompt", prompt="review this code, don't change anything")
    assert decision(guarded.send("pre-tool", **guarded.edit("app.py", "x = 1", "x = 2"))) == "deny"


def test_guard_sends_nothing_back_at_stop(guarded):
    guarded.send("user-prompt", prompt="fix it")
    guarded.do(guarded.edit("billing/invoice.py", "x = 1", "x = 2"))
    assert guarded.send("stop", last_assistant_message="Done. All tests pass.") == {}


@pytest.mark.parametrize("value", ["guard", "GUARD", "Guard", " guard", " off", "OFF", "\\u006fff"])
def test_turning_the_hooks_down_needs_a_person_however_it_is_spelled(session, value):
    event = {"tool_name": "Edit", "tool_input": {"file_path": str(session.project / ".claude" / "settings.json"), "old_string": "{}",
                                                 "new_string": '{"env": {"OCCAM_HOOKS": "%s"}}' % value}}
    assert decision(session.send("pre-tool", **event)) == "ask"


# ---------------------------------------------------------------- routed language skills
# The user chose on 2026-11-08 to take the language skills off the always-on listing. They can't be loaded with the Skill tool
# then, so the hooks name the file to read: on the first edit in that language, and on a review, which makes no edit.

LANGUAGE_FILE = re.compile(r"/skills/(occam-[a-z]+)/SKILL\.md")


def pointed_to(text):
    found = LANGUAGE_FILE.findall(text)
    for name in found:
        assert (ROOT / "plugin" / "skills" / name / "SKILL.md").is_file(), name
    return set(found)


def test_an_edit_points_to_its_languages_file_once(session):
    session.send("user-prompt", prompt="fix it")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"}, tool_response={})
    first, _ = session.do(session.edit("web/app.ts", "let x = 1", "let x = 2"))
    assert pointed_to(said(first)) == {"occam-typescript"}
    again, _ = session.do(session.edit("web/app.ts", "let x = 2", "let x = 3"))
    assert not pointed_to(said(again))


def test_reading_the_languages_file_counts_as_having_it(session):
    session.send("user-prompt", prompt="fix it")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"}, tool_response={})
    path = str(ROOT / "plugin" / "skills" / "occam-go" / "SKILL.md")
    session.send("post-tool", tool_name="Read", tool_input={"file_path": path}, tool_response={})
    before, _ = session.do(session.edit("main.go", "x := 1", "x := 2"))
    assert not pointed_to(said(before))


@pytest.mark.parametrize("prompt, language", [
    ("Review the Go service in main.go", "occam-go"),
    ("review only: is this TypeScript reducer sound?", "occam-typescript"),
    ("Review the Rust crate's error handling", "occam-rust"),
    ("Review the Kotlin repository layer", "occam-jvm"),
    ("Review the C++ parser for undefined behavior", "occam-cpp"),
    ("Review this SQL migration", "occam-sql"),
    ("Review deploy.sh, don't change anything", "occam-shell"),
    ("Review this pull request in app.py", "occam-python"),
])
def test_a_review_finds_the_guidance_for_the_language_it_names(session, prompt, language):
    assert language in pointed_to(said(session.send("user-prompt", prompt=prompt)))


def test_a_review_naming_no_language_gets_the_projects(session):
    (session.project / "Cargo.toml").write_text("[package]\n")
    assert pointed_to(said(session.send("user-prompt", prompt="Review this repo, read-only"))) == {"occam-rust"}


@pytest.mark.parametrize("prompt", ["Review the plan: should we go ahead?", "Review plan C", "Review the doc, no code changes"])
def test_ordinary_words_name_no_language(session, prompt):
    assert not pointed_to(said(session.send("user-prompt", prompt=prompt)))


def test_a_language_is_pointed_to_once_per_session(session):
    assert pointed_to(said(session.send("user-prompt", prompt="Review main.go"))) == {"occam-go"}
    assert not pointed_to(said(session.send("user-prompt", prompt="Now review handler.go")))


def test_parallel_first_calls_give_the_card_once(session):
    """Several reads at once are a common first move, and their hooks run at once."""
    session.send("user-prompt", prompt="what does this do?")
    path = session.project / "app.py"
    path.write_text("x = 1\n")
    event = json.dumps({"session_id": "s1", "cwd": str(session.project), "tool_name": "Read", "tool_input": {"file_path": str(path)}, "tool_response": {}})
    runs = [subprocess.Popen([sys.executable, str(HOOK), "post-tool"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=session.env) for _ in range(6)]
    for run in runs:  # every hook has its input before any finishes, so they decide at the same time
        run.stdin.write(event)
        run.stdin.close()
    outputs = [run.stdout.read() for run in runs]
    for run in runs:
        run.wait(timeout=60)
    assert sum(rule_card.RULES in json.loads(out)["hookSpecificOutput"]["additionalContext"] for out in outputs if out.strip()) == 1


@pytest.mark.parametrize("prompt, language", [
    ("Review `app.py` for bugs", "occam-python"),
    ("Review `parser.c` for undefined behavior", "occam-cpp"),
    ("Review `deploy.sh`, don't change anything", "occam-shell"),
    ("Review `migrations/001_add.sql`", "occam-sql"),
])
def test_a_quoted_file_name_names_its_language(session, prompt, language):
    assert language in pointed_to(said(session.send("user-prompt", prompt=prompt)))


@pytest.mark.parametrize("prompt", ["Review how the client should react to timeouts", "Review the spring release checklist",
                                    "Review the scripts in C:\\work\\tools", "Review the port in C#",
                                    "Review the plan in C/D", "Review the folder in C\\work"])
def test_ordinary_words_dont_push_out_the_projects_language(session, prompt):
    (session.project / "pyproject.toml").write_text("")
    assert pointed_to(said(session.send("user-prompt", prompt=prompt))) == {"occam-python"}


@pytest.mark.parametrize("read", [
    {"tool_name": "Read", "tool_input": {"file_path": "C:\\plugins\\occam\\skills\\occam-go\\SKILL.md"}},
    {"tool_name": "Bash", "tool_input": {"command": "cat ../occam-go/SKILL.md"}},
])
def test_reading_the_languages_file_counts_in_other_path_forms(session, read):
    session.send("user-prompt", prompt="fix it")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"}, tool_response={})
    session.send("post-tool", **read, tool_response={})
    before, _ = session.do(session.edit("main.go", "x := 1", "x := 2"))
    assert not pointed_to(said(before))


def test_a_named_language_adds_to_the_projects(session):
    (session.project / "pyproject.toml").write_text("")
    assert pointed_to(said(session.send("user-prompt", prompt="Review the Go service in main.go"))) == {"occam-go", "occam-python"}


@pytest.mark.parametrize("prompt, language", [
    ("review my react app for bugs", "occam-typescript"),
    ("Review our spring boot service", "occam-jvm"),
    ("Review this function written in C: it leaks memory", "occam-cpp"),
])
def test_lowercase_framework_names_and_a_colon_after_c_still_name_the_language(session, prompt, language):
    assert language in pointed_to(said(session.send("user-prompt", prompt=prompt)))


def test_the_card_isnt_repeated_after_its_marker_is_swept(session):
    """The sweep removes week-old markers while a long session's record lives on."""
    session.send("user-prompt", prompt="fix it")
    assert rule_card.RULES in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))
    (Path(session.env["CLAUDE_PLUGIN_DATA"]) / "sessions" / "s1.card").unlink()
    assert rule_card.RULES not in said(session.send("pre-tool", tool_name="Bash", tool_input={"command": "ls"}))
