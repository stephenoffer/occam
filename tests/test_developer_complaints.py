"""Three checks taken from what developers most often say goes wrong with coding agents, researched 2026-11-06.

- "Shall I implement it?" "No." The agent goes ahead anyway.
- Fake integrations: a failure reported as success, a fallback to fake data, a mock in production code.
- Summary and report files nobody asked for.

None of this is measured on an agent. These pin what the hooks say and hold, through the real hook scripts.
"""

import sys
from pathlib import Path

import pytest
from test_hook_scan import Codex, additional, codex, write  # noqa: F401  (codex is a fixture)
from test_lean_core import Session, decision, said, spec
from test_occam_hook import Agent

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

from classify import REFUSAL, asks_to_act, declines  # noqa: E402

ASKED = "I found the cause: the heading is read from the wrong column. Shall I implement the fix?"
# An ordinary file and request, so the only thing that could hold this edit is the refusal.
EDIT = ("app.py", "heading = 1", "heading = 2")


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


@pytest.fixture
def guarded(tmp_path):
    return Session(tmp_path, level="guard")


def answered(session, message, reply):
    session.send("user-prompt", prompt="why does the page show the wrong heading?")
    session.send("stop", last_assistant_message=message)
    return said(session.send("user-prompt", prompt=reply))


# ---------------------------------------------------------------- "no" means no


@pytest.mark.parametrize("reply", ["No", "no.", "Nope", "not yet", "No thanks", "No, leave it as is", "no, don't change anything",
                                   "No. Just explain it.", "nah, I'll do it myself", "Not now, let's discuss first", "stop", "wait"])
def test_a_refusal_to_the_question_holds_edits_for_the_turn(session, reply):
    note = answered(session, ASKED, reply)
    assert "said no" in note
    held = session.send("pre-tool", **session.edit(*EDIT))
    assert decision(held) == "deny" and "the user said no" in spec(held)["permissionDecisionReason"]


def test_the_guard_level_keeps_the_hold(guarded):
    guarded.send("user-prompt", prompt="why does the page show the wrong heading?")
    guarded.send("stop", last_assistant_message=ASKED)
    guarded.send("user-prompt", prompt="no")
    assert decision(guarded.send("pre-tool", **guarded.edit(*EDIT))) == "deny"


@pytest.mark.parametrize("reply", ["No, use the shared formatter instead", "no, fix the other bug first", "No - add a test too",
                                   "nope, the second option", "Not yet, first add logging", "No, implement option B", "no worries, go ahead"])
def test_a_no_that_redirects_the_work_is_not_a_refusal(session, reply):
    answered(session, ASKED, reply)
    assert decision(session.send("pre-tool", **session.edit(*EDIT))) != "deny"


@pytest.mark.parametrize("message", ["Should I keep the old heading helper?", "Shall I fix it now or leave it for later?",
                                     "Done. The heading is fixed and the tests pass.", "Shall I implement it? Here is the plan first."])
def test_no_is_only_a_refusal_after_a_question_about_doing_work(session, message):
    answered(session, message, "No")
    assert decision(session.send("pre-tool", **session.edit(*EDIT))) != "deny"


def test_the_last_stop_is_the_one_answered(session):
    session.send("user-prompt", prompt="why does the page show the wrong heading?")
    session.send("stop", last_assistant_message=ASKED)
    session.send("stop", last_assistant_message="Here is what I found. The heading comes from the wrong column.")
    session.send("user-prompt", prompt="no")
    assert decision(session.send("pre-tool", **session.edit(*EDIT))) != "deny"


def test_the_next_prompt_lifts_it(session):
    answered(session, ASKED, "no")
    session.send("stop", last_assistant_message="Understood, I won't change it. The cause is the column.")
    session.send("user-prompt", prompt="ok, fix it now")
    assert decision(session.send("pre-tool", **session.edit(*EDIT))) != "deny"


def test_a_subagent_asking_doesnt_count(session):
    session.send("user-prompt", prompt="why does the page show the wrong heading?")
    session.send("stop", last_assistant_message="Done.")
    session.send("stop", agent_id="a1", last_assistant_message=ASKED)
    session.send("user-prompt", prompt="no")
    assert decision(session.send("pre-tool", **session.edit(*EDIT))) != "deny"


@pytest.mark.parametrize("message, asks", [
    ("Want me to apply this fix?", True), ("**Shall I proceed?**", True), ("Do you want me to update the tests?", True), ("Do you want me to update the tests as well?", False),  # an extra step: "no" skips it
    ("Would you like me to make these changes?", True), ("Should I go ahead and commit?", True),
    ("Should I keep the old API?", False), ("Is this the behavior you expected?", False), ("What did you mean by total?", False),
    ("Should I add the index, or would a cache be better?", False), ("", False),
])
def test_what_counts_as_asking_to_act(message, asks):
    assert asks_to_act(message) is asks


def test_a_refusal_needs_the_question():
    assert REFUSAL.match("No") and not declines("No", asked_to_act=False) and declines("No", asked_to_act=True)


def test_codex_holds_edits_after_a_refusal_too(codex):
    codex.send("user-prompt", prompt="why does the page show the wrong heading?")
    codex.send("stop", last_assistant_message=ASKED)
    codex.send("user-prompt", prompt="No")
    denied = codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n"})
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "the user said no" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    codex.send("stop", last_assistant_message="Understood.")
    codex.send("user-prompt", prompt="No")
    assert codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n"}) is None


# ---------------------------------------------------------------- fake integrations, said as they're written

FAKES = {
    "failure-reported-as-success": "def save(row):\n    try:\n        db.insert(row)\n    except ValueError:\n        return {'success': True}\n",
    "fallback-fake": "def rows():\n    try:\n        return fetch()\n    except OSError:\n        return mock_rows()\n",
    "mock-in-production": "from unittest.mock import MagicMock\n\nclient = MagicMock()\n",
}


@pytest.mark.parametrize("rule", sorted(FAKES))
def test_a_fake_integration_is_mentioned_when_written(tmp_path, rule):
    agent = Agent(tmp_path)
    agent.prompt("connect the export to the real database")
    agent.load()
    write(agent, "app/store.py", "def save(row):\n    return db.insert(row)\n")
    agent.try_edit("app/store.py")
    write(agent, "app/store.py", FAKES[rule])
    assert rule in additional(agent.edit("app/store.py"))
    agent.bash("python3 -m pytest -q", output="1 passed")
    assert rule not in additional(agent.stop()), "said once as a note, never a send-back (DESIGN.md: no-new-send-backs)"


# ---------------------------------------------------------------- report files nobody asked for


def write_new(session, name, content="# Summary\n\nFixed the rounding.\n"):
    return {"tool_name": "Write", "tool_input": {"file_path": str(session.project / name), "content": content}}


@pytest.mark.parametrize("name", ["IMPLEMENTATION_SUMMARY.md", "FIX_REPORT.md", "docs/REFACTORING_COMPLETE.md", "PROGRESS.md"])
def test_an_unrequested_report_file_is_held_once(session, name):
    session.send("user-prompt", prompt="fix the rounding in the invoice total")
    held = session.send("pre-tool", **write_new(session, name))
    assert decision(held) == "deny" and "final message" in spec(held)["permissionDecisionReason"]
    assert decision(session.send("pre-tool", **write_new(session, name, "# Summary\n\nDifferent words.\n"))) != "deny"


@pytest.mark.parametrize("prompt", ["fix the rounding and write a summary of what changed", "fix it, and add notes for the team",
                                    "update the docs after the fix", "fix it and put the write-up in FIX_REPORT.md"])
def test_a_requested_report_goes_ahead(session, prompt):
    session.send("user-prompt", prompt=prompt)
    assert decision(session.send("pre-tool", **write_new(session, "FIX_REPORT.md"))) != "deny"


def test_ordinary_documents_and_existing_reports_go_ahead(session):
    session.send("user-prompt", prompt="fix the rounding in the invoice total")
    assert decision(session.send("pre-tool", **write_new(session, "README.md"))) != "deny"
    assert decision(session.send("pre-tool", **write_new(session, "docs/rounding.md"))) != "deny"
    (session.project / "PROGRESS.md").write_text("# Progress\n")
    assert decision(session.send("pre-tool", **write_new(session, "PROGRESS.md"))) != "deny"


def test_guard_doesnt_hold_a_report(guarded):
    guarded.send("user-prompt", prompt="fix the rounding")
    assert guarded.send("pre-tool", **write_new(guarded, "IMPLEMENTATION_SUMMARY.md")) == {}


def test_a_subagent_isnt_held_for_a_report(session):
    session.send("user-prompt", prompt="fix the rounding")
    assert decision(session.send("pre-tool", agent_id="a1", **write_new(session, "IMPLEMENTATION_SUMMARY.md"))) != "deny"


# ---------------------------------------------------------------- what a fresh review found, 2026-11-06

FAKE_KEY = "AKIA" + "A" * 16  # built here so no credential shape sits in the repository


def test_writing_a_held_report_again_still_meets_the_secret_hold(session):
    session.send("user-prompt", prompt="fix the rounding in the invoice total")
    event = write_new(session, "IMPLEMENTATION_SUMMARY.md", f"aws_access_key_id = {FAKE_KEY}\n")
    assert "report" in spec(session.send("pre-tool", **event))["permissionDecisionReason"]
    again = session.send("pre-tool", **event)
    assert decision(again) == "deny" and "looks like" in spec(again)["permissionDecisionReason"]


@pytest.mark.parametrize("prompt, name", [
    ("write a guide to our deploy workflow", "docs/workflow.md"), ("create a checklist for code reviewers", "REVIEW_CHECKLIST.md"),
    ("add a parser test that compares against a fixture file", "tests/data/fixture_output.txt"),
    ("add a golden file for the formatter test", "tests/golden/final_output.txt"), ("fix the scheduler", "docs/tasks.md"),
    ("fix the scheduler", "docs/workers.md"), ("fix the scheduler", "CHANGELOG.md"),
])
def test_ordinary_files_with_report_words_are_not_held(session, prompt, name):
    session.send("user-prompt", prompt=prompt)
    assert decision(session.send("pre-tool", **write_new(session, name))) != "deny"


@pytest.mark.parametrize("message", [
    "Found it. Should I keep the old endpoint around while we migrate?", "Found it. Should I keep the old API and add a shim?",
    "Found it. Should I wait for your review before I commit?", "Found it. Should I hold off on the refactor until after the release?",
    "Found it. Should I leave the refactor for a separate PR?", "Found it. Should I reuse the existing helper rather than write a new one?",
    "Found it. Should I avoid any change to the public interface?",
])
def test_no_to_a_question_where_no_means_go_ahead_holds_nothing(session, message):
    answered(session, message, "no")
    assert decision(session.send("pre-tool", **session.edit(*EDIT))) != "deny"


@pytest.mark.parametrize("reply", ["no don't touch the tests fix it", "no just tell me why and then fix it", "no, don't edit the migration files"])
def test_a_no_with_work_in_it_is_not_a_refusal(reply):
    assert not declines(reply, asked_to_act=True)


def test_the_patterns_stay_fast_on_huge_input():
    import time
    started = time.monotonic()
    for message in (" " * 40000, "_" * 40000, "x" + " " * 40000 + "?"):
        asks_to_act(message)
    declines("no, " + "don't change " * 22 + "a b c d e f g h .", asked_to_act=True)
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize("name", ["polls/tests.py", "app/testing.py", "app/fixtures.py", "src/pkg/pytest_plugin.py", "noxfile.py", "docs/conf.py", "scripts/seed.py"])
def test_test_support_and_docs_dont_hear_about_mocks(tmp_path, name):
    agent = Agent(tmp_path)
    agent.prompt("add a test helper")
    agent.load()
    write(agent, name, "VALUE = 1\n")
    agent.try_edit(name)
    write(agent, name, FAKES["mock-in-production"])
    assert "mock-in-production" not in additional(agent.edit(name))


def test_a_declined_turn_gets_no_review_notes(session):
    note = answered(session, ASKED, "no")
    assert "said no" in note and "covers code review" not in note


def test_codex_clears_the_question_once_answered(codex):
    codex.send("user-prompt", prompt="why does the page show the wrong heading?")
    codex.send("stop", last_assistant_message=ASKED)
    codex.send("user-prompt", prompt="what about the footer?")
    codex.send("user-prompt", prompt="No")  # the turn before never reached Stop
    assert codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n"}) is None


def test_codex_ignores_a_subagent_asking_and_doesnt_send_back_a_held_turn(codex):
    codex.send("user-prompt", prompt="why does the page show the wrong heading?")
    codex.send("stop", agent_id="a1", last_assistant_message=ASKED)
    codex.send("user-prompt", prompt="No")
    assert codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n"}) is None
    (codex.project / "app.py").write_text("def charge(card):\n    pass\n")
    codex.send("post-tool", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n"}, tool_response="ok")
    codex.send("stop", last_assistant_message=ASKED)
    codex.send("user-prompt", prompt="No")
    assert codex.send("stop", last_assistant_message="Understood, I won't change it.") is None


# ---------------------------------------------------------------- what a second fresh review found


@pytest.mark.parametrize("message", [
    "Before I implement it, should I add caching too?", "Ready to start. Should I create a feature branch first?",
    "Should I make a backup of the database first?", "Should I add tests before implementing the fix?", "Should I commit after each step?",
])
def test_no_to_an_extra_step_means_skip_it_and_carry_on(session, message):
    answered(session, message, "no")
    assert decision(session.send("pre-tool", **session.edit(*EDIT))) != "deny"


@pytest.mark.parametrize("prompt, name", [
    ("add a test for the parser with an expected output fixture", "tests/fixtures/EXPECTED_STATUS.md"),
    ("set up mdbook for the project", "book/src/SUMMARY.md"), ("add an issue template for bugs", ".github/ISSUE_TEMPLATE/BUG_REPORT.md"),
    ("list the HTTP codes we return", "STATUS_CODES.md"), ("fix the scheduler", "INCOMPLETE.md"),
])
def test_files_that_only_look_like_reports_are_not_held(session, prompt, name):
    session.send("user-prompt", prompt=prompt)
    assert decision(session.send("pre-tool", **write_new(session, name))) != "deny"


@pytest.mark.parametrize("path, shipped", [
    ("src/ab_test.py", True), ("lims/samples/service.py", True), ("app/docs/views.py", True), ("src/examples/run.py", True),
    ("app/fixture.py", True), ("app/store.py", True), ("polls/tests.py", False), ("tests/unit/helpers.py", False), ("docs/conf.py", False),
])
def test_only_test_support_and_top_level_docs_are_exempt(path, shipped):
    """The hook's own decision. The scanner has path rules of its own, and may stay quiet on some of these anyway."""
    import scan_notes
    finding = {"rule": "mock-in-production", "confidence": "medium", "severity": "medium", "path": path}
    assert scan_notes._is_serious(finding) is shipped


@pytest.mark.parametrize("reply", ["no, stop", "no, wait", "no no", "no, don't do it yet", "no just leave it", "No, I don't want that"])
def test_more_plain_refusals(reply):
    assert declines(reply, asked_to_act=True)


@pytest.mark.parametrize("message", ["Want me to open a PR?", "Ready to apply?", "Shall I?", "I can implement this now. Want me to?",
                                     "Do you want me to take care of it?", "Should I go ahead with the migration?"])
def test_more_ways_of_asking_to_do_the_work(message):
    assert asks_to_act(message)
