"""Reviews and reports are the costliest things the hook asks for, so it asks early and asks for no more than is needed."""

import pytest

from test_occam_hook import Agent, added


@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path)


def test_a_high_consequence_edit_asks_for_the_review_before_the_report_once(agent):
    agent.prompt("Fix it")
    agent.load()
    assert added(agent.edit("app.py")) == "" or "occam:code-reviewer" not in added(agent.edit("app.py"))
    first = added(agent.edit("auth/login.py"))
    assert "occam:code-reviewer" in first and "before you write your report" in first
    assert "occam:code-reviewer" not in added(agent.edit("auth/login.py"))


def test_a_high_consequence_edit_through_the_shell_asks_for_the_review_too(agent):
    agent.prompt("Fix it")
    agent.load()
    assert "before you write your report" in added(agent.bash("sed -i '' 's/a/b/' auth/login.py"))


def test_a_subagent_isnt_the_one_asked_to_get_a_review(agent):
    agent.prompt("Fix it")
    agent.load()
    output = agent.send("post-tool", tool_name="Edit", tool_input={"file_path": agent.path("auth/login.py")}, agent_id="a1")
    assert "before you write your report" not in added(output)


def test_a_second_review_needs_only_what_changed_since_the_first(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.edit("auth/login.py")
    agent.bash("pytest", output="1 passed")
    first = added(agent.stop("1 passed"))
    assert "the requirements and the diff" in first and "only what changed" not in first
    agent.review()
    agent.edit("auth/login.py")
    agent.bash("pytest", output="1 passed")
    second = added(agent.stop("1 passed"))
    assert "occam:code-reviewer" in second and "covered the whole diff" in second and "that review's findings" in second
    assert "Otherwise it needs the requirements and the diff" in second, "a review that was partial or blocked looks the same in the record"


def test_a_review_for_an_earlier_request_doesnt_shrink_the_next_one(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.edit("auth/login.py")
    agent.bash("pytest", output="1 passed")
    agent.review()
    assert agent.stop("1 passed") is None
    agent.prompt("Now fix the other thing")
    agent.edit("auth/session.py")
    agent.bash("pytest", output="1 passed")
    said = added(agent.stop("1 passed"))
    assert "the requirements and the diff" in said and "only what changed" not in said


def test_a_later_request_hears_about_the_review_again(agent):
    agent.prompt("Fix it")
    agent.load()
    assert "before you write your report" in added(agent.edit("auth/login.py"))
    agent.prompt("Now the other thing")
    assert "before you write your report" in added(agent.edit("auth/session.py"))


def test_a_coordinator_hears_about_the_review_when_a_delegated_edit_comes_back(agent):
    agent.prompt("Fix it")
    agent.load()
    agent.send("post-tool", tool_name="Edit", tool_input={"file_path": agent.path("auth/login.py")}, agent_id="a1")
    output = agent.send("post-tool", tool_name="Agent", tool_input={"subagent_type": "general-purpose"})
    assert "before you write your report" in added(output)
