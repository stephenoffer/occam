"""occam's typed commands, `/occam:razor`, `/occam:review` and `/occam:audit`, through the real hook scripts.

Each command names the kind of request it is, so the hook reads it the way those words would read: a review holds edits, and an audit
holds them unless it asks for a fix. None of them counts as loading the core skill, which consequential edits still wait for.
"""

import sys
from pathlib import Path

import pytest
import test_hook_scan
from test_lean_core import Session, decision, spec

codex = test_hook_scan.codex  # pytest finds a fixture by its name here; an assignment, unlike an import, isn't read as shadowed by the tests' parameter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

from classify import reads_as_read_only, visible_prompt  # noqa: E402

PLAIN = ("app.py", "heading = 1", "heading = 2")
# Consequential by its path, so it waits for the core skill.
AUTH = ("auth.py", "allowed = False", "allowed = True")


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


def reason(output):
    return spec(output).get("permissionDecisionReason", "")


@pytest.mark.parametrize("prompt", ["/occam:review", "/occam:review app.py", "/occam:review user.py", "/occam:audit", "/occam:audit src/"])
def test_a_typed_review_or_audit_holds_edits(session, prompt):
    session.send("user-prompt", prompt=prompt)
    held = session.send("pre-tool", **session.edit(*PLAIN))
    assert decision(held) == "deny" and "review-only or plan-only" in reason(held)


def test_an_audit_that_asks_for_a_fix_can_edit(session):
    session.send("user-prompt", prompt="/occam:audit src/ and fix what you find")
    assert decision(session.send("pre-tool", **session.edit(*PLAIN))) != "deny"


def test_the_razor_is_a_request_to_edit(session):
    session.send("user-prompt", prompt="/occam:razor app.py")
    assert decision(session.send("pre-tool", **session.edit(*PLAIN))) != "deny"


@pytest.mark.parametrize("prompt", ["/occam:razor auth.py", "/occam:review", "/occam:audit and fix it"])
def test_a_command_doesnt_count_as_loading_the_core_skill(session, prompt):
    session.send("user-prompt", prompt=prompt)
    session.send("user-prompt", prompt="go ahead and make the change")
    held = session.send("pre-tool", **session.edit(*AUTH))
    assert decision(held) == "deny" and "`occam:occam` skill has not been loaded" in reason(held)


def test_typing_the_core_skill_still_counts_as_loading_it(session):
    session.send("user-prompt", prompt="/occam:occam tighten the check in auth.py")
    assert decision(session.send("pre-tool", **session.edit(*AUTH))) != "deny"


@pytest.mark.parametrize("prompt", [
    # Words in the arguments that would lift a plain-words review don't lift a typed one.
    "/occam:review, then tell me if we should go ahead with the merge",
    "/occam:review whether the plan to make the change is sound",
    "/occam:review my branch; you can edit the docs later",
    # Paths and nouns that collide with the free-text audit rules.
    "/occam:audit logging/", "/occam:audit trail.py", "/occam:audit build/", "/occam:audit src/add.py",
    "/occam:audit only tokens.py", "/occam:audit the update path", "  /OCCAM:AUDIT\nsrc/",
])
def test_a_typed_review_or_audit_holds_whatever_its_arguments_say(session, prompt):
    session.send("user-prompt", prompt=prompt)
    held = session.send("pre-tool", **session.edit(*PLAIN))
    assert decision(held) == "deny" and "review-only or plan-only" in reason(held)


@pytest.mark.parametrize("prompt", ["/occam:audit src and remove the dead code", "/occam:audit harden src/", "/occam:audit src/ then clean up"])
def test_an_audit_asking_for_any_repair_can_edit(session, prompt):
    session.send("user-prompt", prompt=prompt)
    assert decision(session.send("pre-tool", **session.edit(*PLAIN))) != "deny"


@pytest.mark.parametrize("prompt, held", [("/occam:review src/", True), ("/occam:audit logging/", True),
                                          ("/occam:audit src/ and fix it", False), ("/occam:razor src/", False)])
def test_codex_reads_the_commands_the_same_way(codex, prompt, held):
    codex.send("user-prompt", prompt=prompt)
    patch = "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n"
    output = codex.send("pre-tool", tool_name="apply_patch", tool_input={"command": patch})
    assert (decision(output) == "deny") is held


def test_commands_read_as_the_request_they_name():
    assert visible_prompt("/occam:review src/").startswith("review-only")
    assert visible_prompt("/occam:audit src/").startswith("audit")
    assert visible_prompt("/occam:razor src/") == "/occam:razor src/"
    assert visible_prompt("please /occam:review this") == "please /occam:review this"
    assert reads_as_read_only(visible_prompt("/occam:audit"))
    assert not reads_as_read_only(visible_prompt("/occam:audit and fix it"))
    assert not reads_as_read_only(visible_prompt("/occam:razor"))
