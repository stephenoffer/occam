"""The shared design doc in the hook: what an agent is told when it edits a file, and that nothing can break the edit."""

from pathlib import Path

import pytest

from design_support import Agent, DOC, _git_agent, _write, additional

pytest_plugins = ("design_support",)  # its `repo` and `agent` fixtures


def test_an_edit_to_a_decided_file_hears_the_decision_once(agent):
    _write(agent, "DESIGN.md", DOC)
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    first = additional(agent.edit("app/billing.py"))
    assert "use-cents" in first and "maybe-queue" not in first
    assert "use-cents" not in additional(agent.edit("app/billing.py"))


def test_an_edit_elsewhere_hears_nothing(agent):
    _write(agent, "DESIGN.md", DOC)
    _write(agent, "other.py", "print(1)\n")
    agent.try_edit("other.py")
    assert "DESIGN.md" not in additional(agent.edit("other.py"))


def test_no_design_doc_costs_nothing(agent):
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    assert "DESIGN" not in additional(agent.edit("app/billing.py"))


def test_a_broken_design_doc_cannot_break_an_edit(agent):
    _write(agent, "DESIGN.md", "\x00\x01 not a document ``` ## ## - [")
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    assert "DESIGN.md has" not in additional(agent.edit("app/billing.py"))


def test_the_hook_finds_the_doc_from_a_subfolder(agent):
    _git_agent(agent)
    _write(agent, "DESIGN.md", DOC)
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    done = agent.send("post-tool", cwd=str(agent.project / "app"), tool_name="Edit", tool_input={"file_path": agent.path("app/billing.py")})
    assert "use-cents" in additional(done)


def test_a_document_in_the_working_folder_does_not_speak_for_a_file_outside_it(agent):
    _git_agent(agent)
    _write(agent, "pkg/DESIGN.md", DOC.replace("Money is integer cents", "Pkg billing is in dollars"))
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    done = agent.send("post-tool", cwd=str(agent.project / "pkg"), tool_name="Edit", tool_input={"file_path": agent.path("app/billing.py")})
    assert "dollars" not in additional(done)


def test_the_hook_reads_the_worktree_it_is_editing(agent):
    _git_agent(agent)
    _write(agent, "wt/.git", "gitdir: elsewhere\n")
    _write(agent, "wt/DESIGN.md", DOC)
    _write(agent, "wt/app/billing.py", "print(1)\n")
    agent.try_edit("wt/app/billing.py")
    assert "use-cents" in additional(agent.edit("wt/app/billing.py"))


def test_the_note_reads_as_one_sentence(agent):
    _write(agent, "DESIGN.md", DOC)
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    assert ".." not in additional(agent.edit("app/billing.py"))


def test_the_hook_will_not_read_a_huge_document(agent):
    _write(agent, "DESIGN.md", DOC + "line of text here\n" * 300000)
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    assert "use-cents" not in additional(agent.edit("app/billing.py"))


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="no stock python")
def test_the_note_arrives_on_the_stock_python(tmp_path):
    made = Agent(tmp_path, python="/usr/bin/python3")
    made.prompt("change the billing helper")
    made.load()
    _write(made, "DESIGN.md", DOC)
    _write(made, "app/billing.py", "print(1)\n")
    made.try_edit("app/billing.py")
    assert "use-cents" in additional(made.edit("app/billing.py"))


def test_each_subagent_gets_the_note_once(agent):
    _git_agent(agent)
    _write(agent, "DESIGN.md", DOC)
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    edit = {"tool_name": "Edit", "tool_input": {"file_path": agent.path("app/billing.py")}}
    assert "use-cents" in additional(agent.send("post-tool", **edit))
    assert "use-cents" not in additional(agent.send("post-tool", **edit))
    assert "use-cents" in additional(agent.send("post-tool", agent_id="helper-1", **edit))
    assert "use-cents" not in additional(agent.send("post-tool", agent_id="helper-1", **edit))
    assert "use-cents" in additional(agent.send("post-tool", agent_id="helper-2", **edit))


def test_compaction_repeats_the_pointer(agent):
    _git_agent(agent)
    _write(agent, "DESIGN.md", DOC)
    assert "keeps DESIGN.md" in additional(agent.send("session-start", source="compact", cwd=str(agent.project)))


def test_the_hook_passes_on_a_document_far_too_large(agent):
    _git_agent(agent)
    _write(agent, "DESIGN.md", DOC + "x\n" * 150000)
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    done = agent.send("post-tool", tool_name="Edit", tool_input={"file_path": agent.path("app/billing.py")})
    assert "use-cents" not in additional(done)


def test_a_note_that_cuts_a_decision_says_so(agent):
    _git_agent(agent)
    long = "Handlers may call the billing API directly when " * 8
    _write(agent, "DESIGN.md", DOC + f"- 2026-02-01 long [accepted] {long}never otherwise. Why: w. Applies: `app/billing.py`.\n")
    _write(agent, "app/billing.py", "print(1)\n")
    agent.try_edit("app/billing.py")
    note = additional(agent.edit("app/billing.py"))
    assert "...." in note or "... " in note or "...;" in note, note
