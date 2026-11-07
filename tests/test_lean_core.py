"""The rule card, the guard level, the self-review default and the subagent card, taken from Ponytail and Superpowers on 2026-11-06.

None of this is measured on an agent. These pin what the hooks say and hold, through the real hook script.
"""

import json
import os
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


def test_a_session_starts_with_the_rule_card(session):
    text = said(session.send("session-start", source="startup"))
    assert rule_card.RULES in text and "load the full `occam:occam` skill before editing" in text


def test_compaction_gives_the_card_again_with_the_reload_note(session):
    text = said(session.send("session-start", source="compact"))
    assert rule_card.RULES in text and "Loading `occam:occam` again restores it" in text


def test_an_ordinary_edit_past_the_old_small_size_goes_ahead_under_the_card(session):
    session.send("session-start", source="startup")
    session.send("user-prompt", prompt="fix it")
    before, _ = session.do(session.edit("app.py", "x = 1", ORDINARY))
    assert decision(before) is None
    assert rule_card.RULES not in said(before), "the card was already given at session start"


def test_a_session_that_never_heard_the_card_hears_it_once_before_its_first_edit(session):
    session.send("user-prompt", prompt="fix it")
    first, _ = session.do(session.edit("app.py", "x = 1", "x = 2"))
    second, _ = session.do(session.edit("app.py", "x = 2", "x = 3"))
    assert rule_card.RULES in said(first) and rule_card.RULES not in said(second)


@pytest.mark.parametrize("prompt, name, old, new", [
    ("fix it", "auth.py", "x = 1", "x = 2"),
    ("fix it", "billing/invoice.py", "x = 1", "x = 2"),
    ("fix the authorization check", "app.py", "x = 1", "x = 2"),
    ("speed up the report, it is too slow", "app.py", "x = 1", "x = 2"),
    ("fix it", "app.py", "x = 1", "password = read_password()"),
    ("fix it", "requirements.txt", "a==1", "a==2"),
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


def test_money_and_data_changes_get_a_self_review_note(session):
    session.send("user-prompt", prompt="fix the total")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    _, after = session.do(session.edit("billing/invoice.py", "x = 1", "x = 2"))
    assert "review the whole diff yourself" in said(after) and "code-reviewer" not in said(after)


def test_stop_asks_for_a_stated_self_review_and_accepts_one(session):
    session.send("user-prompt", prompt="fix the total")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    session.do(session.edit("billing/invoice.py", "x = 1", "x = 2"))
    session.check()
    assert "Self-review:" in said(session.send("stop", last_assistant_message="Fixed the total. 3 tests pass. I self-reviewed the whole diff."))
    accepted = said(session.send("stop", last_assistant_message="Fixed the total, 3 tests pass.\n\nSelf-review: no issues found; callers and retries are fine."))
    assert "reviewed" not in accepted and "code-reviewer" not in accepted


def test_saying_it_was_not_reviewed_is_not_a_self_review(session):
    session.send("user-prompt", prompt="fix the total")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    session.do(session.edit("billing/invoice.py", "x = 1", "x = 2"))
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
    _, first = session.do(session.edit("billing/invoice.py", "x = 1", "x = 2"))
    _, second = session.do(session.edit("users/session.py", "x = 1", "x = 2"))
    assert "review the whole diff yourself" in said(first)
    assert "session.py is security-critical" in said(second) and "`occam:code-reviewer` reviews this" in said(second)


def test_the_note_says_why_when_the_request_asks(session):
    session.send("user-prompt", prompt="fix the total and get it reviewed")
    session.send("post-tool", tool_name="Skill", tool_input={"skill": "occam:occam"})
    _, after = session.do(session.edit("billing/invoice.py", "x = 1", "x = 2"))
    assert "the request asks for a review" in said(after) and "security-critical" not in said(after)


@pytest.mark.parametrize("prompt, name", [("fix the login", "app/auth.py"), ("fix the total and get it reviewed", "billing/invoice.py")])
def test_security_critical_changes_or_a_request_still_get_the_fresh_reviewer(session, prompt, name):
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


# ---------------------------------------------------------------- the guard level


def test_guard_says_nothing_at_session_start_or_to_a_subagent(guarded):
    assert guarded.send("session-start", source="startup") == {}
    assert guarded.send("subagent-start", agent_type="general-purpose", agent_id="a1") == {}


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
