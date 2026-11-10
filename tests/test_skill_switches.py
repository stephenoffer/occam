"""occam's switches: the lean core names each module, and the hook states a module once, when its switch turns on.

Through the real hook script, as Claude Code would call it. None of this is measured on an agent.
"""

import sys
from pathlib import Path

import pytest
from test_occam_hook import Agent, added, decision

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugin" / "skills" / "occam"
sys.path.insert(0, str(ROOT / "plugin" / "hooks"))

import skill_switches as switches  # noqa: E402
from classify import BUILD_REQUEST, reads_as_read_only  # noqa: E402

FEATURE = "".join(f"def step_{n}(rows):\n    return [row * {n} for row in rows]\n\n" for n in range(12))  # past the small path's 20 lines


@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path)


def stated(output, name):
    return f"module, also at {SKILL / 'references' / name}.md" in added(output)


def edit(agent, name, old, new):
    path = Path(agent.path(name))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(old)
    event = {"tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}
    before = agent.send("pre-tool", **event)
    path.write_text(path.read_text().replace(old, new))
    return before, agent.send("post-tool", **event)


# ------------------------------------------------------------ the core and its modules agree

def test_the_core_lists_every_module_and_each_says_when_it_turns_on():
    body = (SKILL / "SKILL.md").read_text()
    for name in switches.MODULES:
        assert f"](references/{name}.md)" in body, name
        lines = (SKILL / "references" / f"{name}.md").read_text().split("\n")
        assert lines[0].startswith("# ") and lines[2].startswith("The switch for this turns on"), name


def test_a_statement_is_the_module_without_its_title_or_trigger_line():
    text = switches.statement("bugs")
    assert text.startswith("occam: this request reports a defect") and "A bug's cause is established" in text
    assert "# Bugs" not in text and "The switch for this turns on" not in text


# ------------------------------------------------------------ what the request arms

REVIEW = ["new-code", "findings", "critique"]


@pytest.mark.parametrize("words, expected", [
    ("The totals report crashes on an empty ledger", ["bugs"]),
    ("Add a CSV export to the report command", ["new-code"]),
    ("I need a new endpoint for exports", ["new-code"]),
    ("Implement retries, the upload fails half the time", ["bugs", "new-code"]),
    ("Rename the helper to match the module", []),
    ("Review only: add nothing, just tell me what you'd add", REVIEW),
    ("Review this diff", REVIEW),
    ("Can you review my PR #42?", REVIEW),
    ("Please do a code review of the export module", REVIEW),
    ("Plan and review the migration, review only", REVIEW),
    ("Plan only: how would we add caching here?", ["new-code"]),
    ("Plan the review process changes, plan only", ["new-code"]),
    ("Find out why the export crashes, don't change anything", ["bugs"]),
    ("Implement a CSV export command and open a pull request", ["new-code"]),
    ("Open a pull request with the fix", []),
    ("Rebase my PR #42 onto main", []),
    ("Address the review comments on PR #42", []),
    ("I want to add a review step to the CI pipeline", ["new-code"]),
    ("The diff view breaks on binary files", ["bugs"]),
    ("Why does the audit log drop entries on restart?", []),
    ("The pricing plans page returns 500", []),
    ("Review only: plan-only flags look odd", REVIEW),
    ("Audit the plan for the auth migration", REVIEW),
    ("No, but find out why the export crashes", ["bugs"]),
])
def test_prompt_switches(words, expected):
    read_only = reads_as_read_only(words)  # as user_prompt calls it
    assert switches.prompt_switches(words, read_only, bool(BUILD_REQUEST.search(words)) and not read_only) == expected


def test_a_request_alone_states_nothing_so_a_session_without_code_pays_nothing(agent):
    assert not stated(agent.prompt("Why does this error message say the file is missing?"), "bugs")


def test_loading_the_core_brings_the_modules_the_request_armed_once(agent):
    agent.prompt("The invoice total is wrong when a line has quantity 0, fix it")
    first = agent.load()
    assert stated(first, "bugs") and not stated(first, "new-code")
    assert not stated(agent.load(), "bugs"), "once"
    assert not stated(agent.load("occam:occam-python"), "bugs")


def test_a_review_hears_findings_critique_and_what_should_exist(agent):
    agent.prompt("Review only: is there anything wrong in the new export command?")
    loaded = agent.load()
    assert stated(loaded, "findings") and stated(loaded, "critique") and stated(loaded, "new-code")


def test_a_build_request_mentioning_a_pull_request_doesnt_hear_critique_before_any_diff(agent):
    agent.prompt("Implement a CSV export command and open a pull request")
    loaded = agent.load()
    assert stated(loaded, "new-code") and not stated(loaded, "critique") and not stated(loaded, "findings")


def test_with_the_core_already_loaded_a_new_request_hears_its_modules_at_once(agent):
    agent.prompt("Rename the helper")
    agent.load()
    assert stated(agent.prompt("Now add an export command"), "new-code")


def test_a_module_file_already_read_isnt_stated(agent):
    agent.prompt("Add an export command")
    agent.read_reference("new-code")
    assert not stated(agent.load(), "new-code")


def test_only_this_turns_request_arms_a_module(agent):
    agent.prompt("The export crashes on empty input")
    agent.load()
    agent.send("session-start", source="compact")
    agent.prompt("Rename the helper")
    assert not stated(agent.load(), "bugs"), "the earlier request's work is over"


def test_compaction_states_a_module_again(agent):
    agent.prompt("Add an export command")
    assert stated(agent.load(), "new-code")
    agent.send("session-start", source="compact")
    assert stated(agent.load(), "new-code")


# ------------------------------------------------------------ what an edit turns on

def test_an_edit_that_adds_definitions_turns_on_new_code(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    before, _ = edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    assert stated(before, "new-code")


def test_a_small_edit_that_adds_a_definition_isnt_new_code(agent):
    """Sized on its own, since the hook's small path no longer applies once the core is loaded."""
    agent.prompt("Fix the typo in the helper")
    agent.load()
    before, _ = edit(agent, "helper.py", "def helper():\n    return 1\n", "import os\n\n\ndef helper():\n    return 1\n\n\ndef other():\n    return 2\n")
    assert "module, also at" not in added(before)


def test_a_large_edit_that_only_changes_bodies_isnt_new_code():
    old = "".join(f"def step_{n}(rows):\n    return rows\n" for n in range(15))
    assert not switches.adds_something(False, False, old, old.replace("return rows", "return list(rows)"))
    assert switches.adds_something(False, False, old, "import csv\n" + old)
    assert switches.adds_something(True, False, "", "x = 1\n") and switches.adds_something(False, True, "", "")


def test_a_scan_lead_in_an_edit_turns_on_findings(agent):
    agent.prompt("change the billing helper")
    agent.load()
    _, after = edit(agent, "app.py", "def charge(card):\n    return card.pay()\n", "def charge(card):\n    pass\n")
    assert "stub-body" in added(after) and stated(after, "findings")


# ------------------------------------------------------------ what a check turns on

def test_a_passing_check_after_work_beyond_small_turns_on_done_and_critique_once(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    passed = agent.bash("python3 -m pytest -q", output="4 passed")
    assert stated(passed, "done") and stated(passed, "critique")
    assert not stated(agent.bash("python3 -m pytest -q", output="4 passed"), "done")


def test_a_passing_check_after_a_small_edit_turns_on_nothing(agent):
    agent.prompt("Tweak the helper")
    agent.load()
    edit(agent, "helper.py", "def helper():\n    return 1\n", "def helper():\n    return 2\n")
    assert "module, also at" not in added(agent.bash("python3 -m pytest -q", output="1 passed"))


def test_earlier_turns_dont_count_toward_this_turns_size(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    for n in range(3):
        edit(agent, f"m{n}.py", "X = 1\n", "X = 2\n")
    agent.prompt("Tweak the helper")
    edit(agent, "helper.py", "def helper():\n    return 1\n", "def helper():\n    return 2\n")
    assert "module, also at" not in added(agent.bash("python3 -m pytest -q", ok=False))


def test_an_edit_is_sized_from_what_it_replaced_as_pre_tool_saw_it(agent):
    agent.prompt("Tweak the helper")
    agent.load()
    target = Path(agent.path("big.py"))
    target.write_text("".join(f"X{n} = {n}\n" for n in range(72)))
    event = {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": "X = 1\n"}}
    agent.send("pre-tool", **event)
    target.write_text("X = 1\n")
    agent.send("post-tool", **event)
    assert stated(agent.bash("python3 -m pytest -q", output="1 passed"), "done"), "overwriting 72 lines with one isn't small"


def test_a_tiny_multi_edit_is_small(agent):
    agent.prompt("Tweak the helper")
    agent.load()
    Path(agent.path("helper.py")).write_text("A = 1\n")
    agent.send("post-tool", tool_name="MultiEdit", tool_input={"file_path": agent.path("helper.py"), "edits": [{"old_string": "1", "new_string": "2"}]})
    assert "module, also at" not in added(agent.bash("python3 -m pytest -q", output="1 passed"))


def test_a_run_that_collected_no_tests_turns_on_nothing(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    empty = agent.send("post-failure", tool_name="Bash", tool_input={"command": "python3 -m pytest -q"}, error="Exit code 5\nno tests ran in 0.01s")
    assert "module, also at" not in added(empty)


def test_a_run_that_fails_to_collect_is_a_failure(agent):
    """pytest prints "collected 0 items / 1 error" when an import breaks, which isn't "no tests ran"."""
    agent.prompt("Tidy up the report module")
    agent.load()
    edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    broken = agent.send("post-failure", tool_name="Bash", tool_input={"command": "python3 -m pytest"},
                        error="Exit code 2\ncollected 0 items / 1 error\nE   SyntaxError: invalid syntax\n1 error in 0.11s")
    assert stated(broken, "bugs") and stated(broken, "done")


def test_without_a_pre_tool_record_an_edit_is_sized_as_small_edit_sizes_it(agent):
    agent.prompt("Tweak the helper")
    agent.load()
    old = "".join(f"A{n} = {n}\n" for n in range(12))
    Path(agent.path("helper.py")).write_text(old.replace("= 3", "= 30"))
    agent.send("post-tool", tool_name="Edit", tool_input={"file_path": agent.path("helper.py"), "old_string": old, "new_string": old.replace("= 3", "= 30")})
    assert "module, also at" not in added(agent.bash("python3 -m pytest -q", output="1 passed")), "12 lines for 12 is small, as pre-tool would say"


def test_a_check_with_no_edit_before_it_turns_on_nothing(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    assert "module, also at" not in added(agent.bash("python3 -m pytest -q", output="4 passed"))


def test_a_failing_check_after_work_beyond_small_turns_on_bugs_and_done(agent):
    """Done holds what to say about failures that remain and work that's blocked, which is when checks don't pass."""
    agent.prompt("Tidy up the report module")
    agent.load()
    edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    failed = agent.bash("python3 -m pytest -q", ok=False)
    assert stated(failed, "bugs") and stated(failed, "done") and not stated(failed, "critique")


def test_a_failing_check_after_only_test_edits_isnt_a_bug(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    edit(agent, "tests/test_report.py", "X = 1\n", "X = 1\n\n" + FEATURE.replace("def step_", "def test_step_"))
    failed = agent.bash("python3 -m pytest -q", ok=False)
    assert stated(failed, "done") and not stated(failed, "bugs")


def test_a_failing_check_after_a_small_edit_turns_on_nothing(agent):
    agent.prompt("Tweak the helper")
    agent.load()
    edit(agent, "helper.py", "def helper():\n    return 1\n", "def helper():\n    return 2\n")
    assert "module, also at" not in added(agent.bash("python3 -m pytest -q", ok=False))


# ------------------------------------------------------------ who hears them

def test_without_the_core_loaded_no_module_is_stated(agent):
    """They're part of the core, so ordinary work under the rule card alone hears none of them, as before they moved out."""
    agent.prompt("Add a summary page and fix the crash in the totals")
    before, _ = edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    assert "module, also at" not in added(before) + added(agent.bash("python3 -m pytest -q", output="4 passed"))


def test_the_guard_level_neither_states_nor_uses_up_a_module(agent):
    agent.env["OCCAM_HOOKS"] = "guard"
    agent.prompt("Tidy up the report module")
    agent.load()
    edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    assert not stated(agent.bash("python3 -m pytest -q", output="4 passed"), "done")
    del agent.env["OCCAM_HOOKS"]
    assert stated(agent.bash("python3 -m pytest -q", output="4 passed"), "done"), "nothing was recorded as heard under guard"


def test_a_subagents_check_neither_hears_nor_uses_up_a_module(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    edit(agent, "report.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    sub = agent.send("post-tool", tool_name="Bash", agent_id="a1", tool_input={"command": "python3 -m pytest -q"}, tool_response={"stdout": "4 passed"})
    assert "module, also at" not in added(sub)
    parent = agent.bash("python3 -m pytest -q", output="4 passed")
    assert stated(parent, "done") and stated(parent, "critique")


def test_a_subagents_scan_lead_neither_hears_nor_uses_up_findings(agent):
    agent.prompt("change the billing helper")
    agent.load()
    clean, stub = "def charge(card):\n    return card.pay()\n", "def charge(card):\n    pass\n"
    Path(agent.path("sub.py")).write_text(clean)
    event = {"tool_name": "Edit", "agent_id": "a1", "tool_input": {"file_path": agent.path("sub.py"), "old_string": clean, "new_string": stub}}
    agent.send("pre-tool", **event)
    Path(agent.path("sub.py")).write_text(stub)
    sub = agent.send("post-tool", **event)
    assert "stub-body" in added(sub) and not stated(sub, "findings"), "the subagent's edit raised a lead, and heard no module"
    _, after = edit(agent, "app.py", clean, stub)
    assert stated(after, "findings")


def test_a_module_that_cant_be_read_stays_unheard_and_costs_only_itself(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("OCCAM_HOOKS", raising=False)
    import occam_hook
    event = {"session_id": "unreadable", "cwd": str(tmp_path)}
    occam_hook.record(event, kind="skill", name="occam")
    real = switches.statement

    def broken(name, why=None):
        if name == "done":
            raise FileNotFoundError(name)
        return real(name, why)

    monkeypatch.setattr(switches, "statement", broken)
    notes = occam_hook.module_notes(event, occam_hook.Session(event), ["done", "critique"])
    assert len(notes) == 1 and "Critique, then converge" in notes[0]
    monkeypatch.setattr(switches, "statement", real)
    assert len(occam_hook.module_notes(event, occam_hook.Session(event), ["done", "critique"])) == 1, "done is still unheard, critique isn't"


def test_an_edit_the_hook_cant_size_is_still_recorded(agent):
    agent.prompt("Tidy up the report module")
    agent.load()
    Path(agent.path("report.py")).write_text("X = 1\n")
    agent.send("post-tool", tool_name="Edit", tool_input={"file_path": agent.path("report.py"), "old_string": None, "new_string": 7})
    assert "No check has run since" in str(agent.stop()), "Stop knows about the edit, so it was recorded"


def test_every_trigger_pattern_is_quick_on_hostile_input():
    import time
    from classify import CONSEQUENTIAL_REQUEST, CONSEQUENTIAL_SHELL_PATH
    for pattern in (switches.BUG_PROMPT, switches.BUILD_PROMPT, switches._DEFINES, switches._IMPORTS, CONSEQUENTIAL_REQUEST, CONSEQUENTIAL_SHELL_PATH):
        for text in ("a" * 200_000, " " * 200_000, "def " * 50_000, "import " * 50_000, "\t" * 100_000 + "x", "public\n" * 15_000,
                     "export \n" * 15_000, "pub \n" * 30_000, "from x\n" * 20_000, "const a =\n" * 15_000):
            start = time.perf_counter()
            pattern.findall(text)
            assert time.perf_counter() - start < 1.0, (pattern.pattern[:40], text[:10])


# ------------------------------------------------------------ which work loads the core (the owner's decision, 2026-11-09)

CORE_NOTE = "names security or money work"
SHELL_NOTE = "load it before going further"


def heredoc(path, body="def total(items):\n    return sum(items)\n"):
    return f"mkdir -p {Path(path).parent} && cat > {path} <<'PY'\n{body}PY"


def test_the_core_description_names_what_loads_it_and_sends_ordinary_work_to_the_card():
    import yaml
    description = yaml.safe_load((SKILL / "SKILL.md").read_text().split("---")[1])["description"]
    for subject in ("auth", "secrets", "tenancy", "money", "pricing", "migrations", "reviewing code"):
        assert subject in description, subject
    assert "Ordinary feature work and small fixes don't need it." in description


@pytest.mark.parametrize("words", ["Fix the refund rounding in the billing module", "Add OAuth login to the admin site", "Add OAuth2 to the API",
                                   "Write the migration that splits the users table", "The invoice totals are wrong for zero-quantity lines",
                                   "Fix payment_service rounding", "PaymentService double charges", "Fix the sign-in redirect", "Migrate the database to Postgres",
                                   "Add JWT refresh to `api/session.py`", "Update the alembic revision"])
def test_a_request_naming_security_or_money_work_asks_for_the_core(agent, words):
    assert CORE_NOTE in added(agent.prompt(words))


@pytest.mark.parametrize("words", ["Add a CSV export to the report command", "Make the progress bar show a percentage",
                                   "Cut the tokens this tool spends per session", "Rename the helper to match the module",
                                   "git checkout the feature branch and fix the flaky test", "Migrate the tests from unittest to pytest", "Migrate to Python 3.12",
                                   "Fix the taxonomy page", "Add a websocket subscriptions endpoint", "How does the auth flow work here?"])
def test_ordinary_work_runs_on_the_rule_card(agent, words):
    assert CORE_NOTE not in added(agent.prompt(words))


def test_a_review_hears_the_review_note_not_both(agent):
    said = added(agent.prompt("Review only: is the billing change safe?"))
    assert "covers code review and planning" in said and CORE_NOTE not in said


def test_no_core_note_once_the_core_is_loaded(agent):
    agent.prompt("Rename the helper")
    agent.load()
    assert CORE_NOTE not in added(agent.prompt("Now fix the refund rounding in billing"))


def test_the_core_note_comes_once_and_not_in_plan_mode(agent):
    assert CORE_NOTE in added(agent.prompt("Fix the refund rounding in billing"))
    assert CORE_NOTE not in added(agent.prompt("Now fix the invoice rounding too")), "once"


def test_no_core_note_in_plan_mode(agent):
    assert CORE_NOTE not in added(agent.send("user-prompt", prompt="Fix the refund rounding in billing", permission_mode="plan"))


def test_typing_a_language_skill_doesnt_hide_the_core_note(agent):
    assert CORE_NOTE in added(agent.prompt("/occam-python fix the refund rounding in billing"))


def test_a_heredoc_write_to_a_billing_file_says_what_matters_once(agent):
    """Edit tools writing here are held for the core; shell commands are held only for destructive actions, so this is a note."""
    agent.prompt("Tidy up the module")
    first = agent.try_bash(heredoc(agent.path("billing/invoice.py")))
    assert decision(first) is None, "a note, not a hold"
    assert SHELL_NOTE in added(first) and "billing/invoice.py" in added(first) and "Retry only what is safe to repeat" in added(first)
    assert SHELL_NOTE not in added(agent.try_bash(heredoc(agent.path("billing/refund.py")))), "once"


@pytest.mark.parametrize("path", ["shop/pricing.py", "alembic/versions/3f2a_add_col.py", "app/jwt.py", "db/schema.sql", "users/authorization.py"])
def test_a_shell_write_to_any_file_an_edit_would_be_held_on_says_so(agent, path):
    agent.prompt("Tidy up the module")
    assert SHELL_NOTE in added(agent.try_bash(heredoc(agent.path(path))))


def test_no_shell_note_in_plan_mode_or_on_a_read_only_turn(agent):
    agent.prompt("Review only: look over the billing code")
    assert SHELL_NOTE not in added(agent.try_bash(heredoc(agent.path("billing/invoice.py"))))
    agent.prompt("Tidy up the module")
    assert SHELL_NOTE not in added(agent.try_bash(heredoc(agent.path("billing/invoice.py")), permission_mode="plan"))
    assert SHELL_NOTE in added(agent.try_bash(heredoc(agent.path("billing/invoice.py")))), "neither used it up"


def test_the_guard_level_neither_states_nor_uses_up_the_shell_note(agent):
    agent.env["OCCAM_HOOKS"] = "guard"
    agent.prompt("Tidy up the module")
    agent.try_bash(heredoc(agent.path("billing/invoice.py")))
    del agent.env["OCCAM_HOOKS"]
    assert SHELL_NOTE in added(agent.try_bash(heredoc(agent.path("billing/invoice.py"))))


def test_the_shell_note_says_the_security_facts_only_once(agent):
    agent.prompt("Tidy up the module")
    assert "Retry only what is safe to repeat" in added(agent.try_bash(heredoc(agent.path("billing/invoice.py"))))
    agent.load()
    before, _ = edit(agent, "billing/refund.py", "X = 1\n", "X = 1\n\n" + FEATURE)
    assert "Retry only what is safe to repeat" not in added(before)


def test_a_heredoc_write_to_an_ordinary_file_says_nothing_of_the_core(agent):
    agent.prompt("Tidy up the module")
    assert SHELL_NOTE not in added(agent.try_bash(heredoc(agent.path("report/export.py"))))


def test_a_heredoc_write_to_a_billing_file_after_the_core_loaded_says_nothing(agent):
    agent.prompt("Tidy up the module")
    agent.load()
    assert SHELL_NOTE not in added(agent.try_bash(heredoc(agent.path("billing/invoice.py"))))


def test_a_subagents_heredoc_write_neither_hears_nor_uses_up_the_note(agent):
    agent.prompt("Tidy up the module")
    assert SHELL_NOTE not in added(agent.try_bash(heredoc(agent.path("billing/invoice.py")), agent_id="a1"))
    assert SHELL_NOTE in added(agent.try_bash(heredoc(agent.path("billing/invoice.py"))))
