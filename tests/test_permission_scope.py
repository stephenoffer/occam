"""Who may lift a review-only hold, and how: a denial, a report, a hedged or unrelated answer and a bare "continue" keep it; a fix asked for
plainly still goes ahead; a named document is written only where it was named. Cases from the 2026-11-11 audit (O002–O006, O042, O043, O098)."""

import json
import os
import subprocess

import pytest

from test_occam_hook import HOOK, Agent, added, decision


@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path)


@pytest.mark.parametrize("tool_input, tool_response", [
    ({"answers": {"Should I go ahead and fix these?": "No"}}, None),
    ({"answers": {"Should I implement it?": "Not yet, just explain"}}, None),
    ({"answers": {"Which test framework do you prefer?": "pytest"}}, None),
    ({}, None),
    ({}, "ok"),
    ({}, {"answers": {"Should I fix it?": "no thanks"}}),
    # a yes that means not yet, and a yes to a question about the review rather than the code
    ({"answers": {"Should I go ahead and fix these?": "Make no changes"}}, None), ({"answers": {"Should I implement it?": "Implement later, after the review"}}, None),
    ({"answers": {"Should I fix it?": "Yes, but not yet"}}, None), ({"answers": {"Should I fix it?": "Okay, hold off for now"}}, None),
    ({"answers": {"Should I write the findings up in REVIEW.md?": "Yes"}}, None), ({"answers": {"Shall I continue reviewing the remaining modules?": "Yes"}}, None),
    ({"answers": {"Should I update the report?": "Yes"}}, None), ({"answers": {"How would you like to proceed?": "Proceed with the review only"}}, None),
    # Only a plain yes approves: a "no" inside a longer answer, or a yes with conditions, keeps the hold, and the person can say "go ahead".
    ({"answers": {"Should I apply these fixes?": "Okay, don't."}}, None), ({"answers": {"Should I apply these fixes?": "Sure — actually, no"}}, None),
    ({"answers": {"Should I apply these fixes?": "Yes please, but hold on until CI passes"}}, None),
    ({"answers": {"Should I fix the bugs?": "Yes, and don't touch the tests"}}, None), ({"answers": {"How would you like to proceed?": "Apply all fixes"}}, None),
    ({"answers": {"Should I also look at the tests?": "Go ahead"}}, None), ({"answers": {"Shall I proceed with the review of the remaining modules?": "Yes"}}, None),
    # a yes to putting the work off, or to doing none of it, isn't a yes to doing it now
    ({"answers": {"Should I fix them later, in a follow-up PR?": "Yes"}}, None), ({"answers": {"Should I change nothing for now?": "Yes"}}, None),
    ({"answers": {"Should I fix it after you've reviewed the report?": "Yes"}}, None), ({"answers": {"Should I fix them tomorrow?": "Yes"}}, None),
    # a yes to changing the write-up isn't a yes to changing the code
    ({"answers": {"Should I fix the typo in the report?": "Yes"}}, None), ({"answers": {"Should I commit the review notes?": "Yes"}}, None),
    ({"answers": {"Should I update the plan to include the migration?": "Yes"}}, None), ({"answers": {"Should I update REVIEW.md?": "Yes"}}, None),
    ({"answers": {"Should I fix them in the next PR?": "Yes"}}, None),
])
def test_answering_a_question_isnt_approval_unless_it_says_yes_to_the_work(agent, tool_input, tool_response):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    agent.load("occam:occam-python")
    agent.send("post-tool", tool_name="AskUserQuestion", tool_input=tool_input, tool_response=tool_response)
    assert decision(agent.try_edit()) == "deny"


@pytest.mark.parametrize("prompt", [
    "Review only. Do not go ahead with edits.",
    "Review only. Don't go ahead and fix anything.",
    "/occam:audit src/ and do not fix anything",
    "Audit the repo and write a report",
    "Audit the code. Write the findings up as a short report.",
    "Review only. You must not go ahead with edits.", "Review only. Do NOT, under any circumstances, go ahead.", "Review only; I will make the changes myself.",
    "Plan only. We will go ahead later.", "Audit src/ and write a report on what to fix", "Audit the repo and write AUDIT.md",
    "Audit the repo; write the results to docs/audit.md", "/occam:audit src/ and list what to fix",
    "Audit the parser. Do not fix the bugs you find.", "Audit the parser. I will fix them myself.", "Audit the repo, but don't fix the issues",
    "Review only. Do not go ahead and make the changes.", "Audit the code and create a plan to fix the bugs.", "Audit the code and write up recommendations for fixes.",
    "Audit the code and write a report on how to fix the bugs.", "Audit the code and propose fixes.", "Audit the code. Make no changes.",
    "Review only; it's not okay to go ahead.", "Review only. If it looks fine, go ahead.", "/occam:audit src/ no fixes please",
    # a go-ahead mentioned, left to the person, asked about or describing the work isn't one given
    "Review only. Ask me before you make the changes.", "Plan only. Once I approve the plan, you can go ahead.", "Review only. Wait for me to say go ahead.",
    "Review only. I'll make the changes.", "Review only. Go ahead and read through the files.", "Review only, and tell me whether it's safe to go ahead.",
    "Audit the code and tell me how to fix the bugs.", "/occam:audit src/ fix nothing", "Audit how we apply the changes to the config",
    "Review only. Do not, for any reason, go ahead.", "Review only. After I've reviewed it, you can go ahead.", "Plan only. Before we go ahead, I want to see the plan.",
    "Review only, the team will make the changes.", "Review only: should we go ahead with this PR?", "Audit the migration code that applies the fixes to old rows.",
    "Review only. Go ahead and look through the code, but don't change anything.", "Review only. Go ahead and review the PR and tell me what to fix.",
    "Review only. Could you check whether I can make the changes safely?", "Review only. When you're done I'll go ahead and make the changes.",
    "Review only: can we go ahead with this PR?", "Review only. Go ahead and summarise the issues.",
    "Review only. You can make the changes after I've read the report.", "Review only. You can fix parser.py later.",
    "Review only, but go ahead and write a report listing the bugs and fixes.", "Review only. Go ahead and review the changes and fixes in this branch.",
    "Review only. Go ahead and fix it after I look at the report.",
])
def test_a_denial_or_a_report_doesnt_lift_a_review_or_audit(agent, prompt):
    assert "held for this turn" in added(agent.prompt(prompt))
    agent.load()
    assert decision(agent.try_edit()) == "deny"


@pytest.mark.parametrize("prompt", [
    "Review it, then go ahead and fix what you find.",
    "/occam:audit src/ and fix the bugs",
    "Audit the repo, fix what you find, and write a report",
    "Go ahead without changing the public API",
    # a report, a later step or a "let me know" in the sentence doesn't take back the fix it also asks for
    "Audit the repo, make a list of the bugs and fix them all", "Audit the code. Make a plan for the fixes and then implement it.",
    "Audit the code and record the results in the tracker, then fix the bugs", "Audit the code, write a report on each bug and fix it",
    "Audit the code and make a list of fixes, then apply them", "Audit and fix the bugs and add docs later", "Audit it. Let me know, then fix the bugs",
    "Audit and stop the leaks by fixing them",
    # a denial or a condition elsewhere in the request doesn't turn a request for a fix into a review
    "Audit the code and I would like you to fix whatever you find", "Audit the repo. Don't touch the tests but fix the bugs",
    "Audit the repo, don't change the API and fix the bugs", "Audit the code. The tests can't pass until you fix the parser",
    "Audit the module and fix anything that could break later", "/occam:audit I would like you to fix the bugs",
    "/occam:audit don't change the API and fix the bugs", "/occam:audit without breaking anything fix the bugs",
    # a denial after the go-ahead limits the fix; it doesn't take the go-ahead back
    "Go ahead and fix the bug without changing the code's behaviour", "Go ahead and fix it, don't make changes to tests",
    "This is no longer review only, so go ahead and fix it, but don't touch the tests",
    # nor does a limit or a condition before it, or a fix asked for by what was suggested, or a limit on what else to touch
    "No need to ask, just go ahead and fix it without changing the code's behaviour.", "If anything looks off, go ahead and fix it, but don't change the code's public API.",
    "Without changing the code's behaviour, go ahead and fix the bug.", "Please don't change the code's public API, just go ahead and fix the bug.",
    "Audit the repo and apply the suggested fixes.", "/occam:audit src/ and apply the suggested fixes", "Fix the typo in the README and touch nothing else.",
    # nor a doubt in another clause, a permission, or a look before the fix
    "It's okay to go ahead and fix it without changing the code's behaviour.", "Not sure whether it's a race, so go ahead and fix it without changing the code's public API.",
    "I'm not sure if I agree, but go ahead and fix it without changing the code's behaviour.", "Go ahead and look into it and fix the bug without changing the code's behaviour.",
    "Audit the repo and then I'd like you to apply the recommended fixes.", "Audit the code and address the findings.",
    "Can we go ahead and fix it without changing the code's behaviour?", "Why don't you go ahead and fix it without changing the code's API?",
    "Audit the service for code that writes secrets to logs and fix it.", "/occam:audit src/ for anything that writes to disk and fix it",
    "If anything looks off go ahead and fix it without changing the code's behaviour.", "Check if the tests pass and go ahead and fix them without changing the code.",
    "Go ahead and make a plan, then implement it without changing the code's API.", "I'd say go ahead and fix it without changing the code's behaviour.",
    "Go ahead and fix the bug that appears after I log in, without changing the code's API.", "Go ahead and fix the crash when I sign in, without changing the code's behaviour.",
])
def test_the_same_words_said_affirmatively_still_allow_edits(agent, prompt):
    assert "held for this turn" not in (added(agent.prompt(prompt)) or "")
    agent.load()
    agent.load("occam:occam-python")
    assert decision(agent.try_edit()) is None


def test_continue_keeps_a_review_only_turn_held(agent):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    agent.load("occam:occam-python")
    agent.stop("Here is the first half of the review.")
    agent.prompt("Continue")
    assert decision(agent.try_edit()) == "deny"
    agent.prompt("ok, keep going")
    assert decision(agent.try_edit()) == "deny"
    agent.prompt("Continue with the review")
    assert decision(agent.try_edit()) == "deny"
    agent.prompt("Now fix the null check in app.py.")
    assert decision(agent.try_edit()) is None


def test_continue_after_asking_to_go_on_reviewing_keeps_the_hold(agent):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    agent.stop("That covers the first five files. Shall I continue with the rest?")
    agent.prompt("Continue")
    assert decision(agent.try_edit()) == "deny"


def test_continue_after_asking_to_do_the_work_is_a_yes(agent):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    agent.load("occam:occam-python")
    agent.stop("I found two bugs. Shall I fix them?")
    agent.prompt("continue")
    assert decision(agent.try_edit()) is None


def test_a_named_report_path_doesnt_allow_the_same_name_elsewhere(agent):
    agent.prompt("Review only and write the findings to docs/report.md")
    agent.load()
    assert decision(agent.try_edit("docs/report.md")) is None
    assert decision(agent.try_edit("production/report.md")) == "deny"
    assert decision(agent.try_edit("report.md")) == "deny"


@pytest.mark.parametrize("prompt, name", [("Review only, and don't update README.md", "README.md"),
                                          ("Review only. Do not add anything to CONTRIBUTING.md", "CONTRIBUTING.md"),
                                          ("Review only. Write a report following CONTRIBUTING.md", "CONTRIBUTING.md"),
                                          ("Review only. Write a report using the format in docs/fmt.md", "docs/fmt.md"),
                                          ("Review only. Write a report per the guidelines in CONTRIBUTING.md", "CONTRIBUTING.md"),
                                          ("Review only: did this add anything to the API that isn't documented in API.md?", "API.md"),
                                          ("Review only. Verify the steps for creating a release in README.md still work.", "README.md"),
                                          ("Review only. Avoid writing to README.md.", "README.md"),
                                          ("Review only. Can you check whether we need to update README.md?", "README.md"),
                                          ("Review only. Check that the functions we add are documented in docs/api.md.", "docs/api.md")])
def test_a_document_named_not_to_change_stays_held(agent, prompt, name):
    (agent.project / name).parent.mkdir(parents=True, exist_ok=True)
    (agent.project / name).write_text("# x\n")
    agent.prompt(prompt)
    agent.load()
    assert decision(agent.try_edit(name)) == "deny"


def test_a_document_named_to_follow_isnt_one_to_write(agent):
    (agent.project / "CONTRIBUTING.md").write_text("# rules\n")
    agent.prompt("Review only. Follow CONTRIBUTING.md and write a report.")
    agent.load()
    assert decision(agent.try_edit("CONTRIBUTING.md")) == "deny"
    assert decision(agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path("REVIEW.md")})) is None
    for name in ("sub/CMakeLists.txt", "CLAUDE.md", "CLAUDE.local.md", "AGENTS.override.md"):  # files that steer a build or an agent aren't a report
        assert decision(agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path(name)})) == "deny", name


def test_an_audit_asking_for_a_report_may_write_a_new_one_but_change_nothing(agent):
    (agent.project / "README.md").write_text("# readme\n")
    agent.prompt("Audit the repo and write a report")
    agent.load()
    assert decision(agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path("AUDIT_REPORT.md")})) is None
    assert decision(agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path("README.md")})) == "deny"
    assert decision(agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path("fix.py")})) == "deny"
    assert decision(agent.try_edit("README.md")) == "deny"


def test_a_line_the_hook_didnt_write_doesnt_switch_it_off(agent):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    with open(agent.project.parent / "data" / "sessions" / "s1.jsonl", "a") as state:
        state.write('[1, 2]\n"text"\n7\n')
    assert decision(agent.try_edit()) == "deny"  # send() also fails on "failed open"


def test_session_state_is_private_to_its_user(agent):
    old = os.umask(0o022)
    try:
        agent.prompt("Fix it")
    finally:
        os.umask(old)
    folder = agent.project.parent / "data" / "sessions"
    assert folder.stat().st_mode & 0o777 == 0o700
    assert (folder / "s1.jsonl").stat().st_mode & 0o777 == 0o600


def test_a_hook_that_fails_open_is_told_to_the_person_once(agent):
    folder = agent.project.parent / "data" / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "s1.jsonl").write_text(json.dumps({"kind": "prompt", "text": 5, "read_only": True}) + "\n")  # a prompt no hook wrote
    event = {"session_id": "s1", "cwd": str(agent.project), "tool_name": "Write", "tool_input": {"file_path": agent.path("notes.md")}}
    done = subprocess.run([agent.python, str(HOOK), "pre-tool"], input=json.dumps(event), capture_output=True, text=True, env=agent.env, timeout=20)
    assert "failed open" in done.stderr
    told = agent.send("session-start", source="startup")
    assert "failed open 1 times" in told["systemMessage"]
    assert "systemMessage" not in (agent.send("session-start", source="startup") or {})


def test_a_failure_is_told_at_guard_level_and_a_bad_log_line_doesnt_keep_the_log(agent):
    folder = agent.project.parent / "data" / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "failed-open.log").write_text('{"hook": "pre-tool", "error": "TypeError: x"}\nnot json\n')
    agent.env["OCCAM_HOOKS"] = "guard"
    told = agent.send("session-start", source="startup")
    assert "failed open 2 times" in told["systemMessage"] and not (folder / "failed-open.log").exists()


def test_a_session_read_again_after_a_record_sees_it(agent):
    import sys
    sys.path.insert(0, str(HOOK.parent))
    import session_state
    os.environ["CLAUDE_PLUGIN_DATA"] = agent.env["CLAUDE_PLUGIN_DATA"]
    try:
        event = {"session_id": "cached"}
        session_state.record(event, kind="prompt", text="one")
        assert len(session_state.Session(event).entries) == 1
        assert len(session_state.Session(event).entries) == 1  # read again unchanged
        session_state.record(event, kind="edit", path="a.py")
        assert [entry["kind"] for entry in session_state.Session(event).entries] == ["prompt", "edit"]
    finally:
        del os.environ["CLAUDE_PLUGIN_DATA"]


def test_the_person_hears_what_the_end_of_turn_scan_didnt_read(agent):
    folder = agent.project.parent / "data" / "sessions"
    agent.prompt("Fix it")
    with open(folder / "s1.jsonl", "a") as state:
        for index in range(10):  # past the eight files a hook scans at the end of a turn
            (agent.project / f"m{index}.py").write_text(f"VALUE_{index} = {index}\n")
            state.write(json.dumps({"kind": "edit", "path": f"m{index}.py", "code": True}) + "\n")
        state.write(json.dumps({"kind": "check", "passed": True}) + "\n")
    told = agent.stop("Done, and the tests pass.") or {}
    assert "didn't read 2 changed files" in (told.get("systemMessage") or json.dumps(told))


@pytest.mark.parametrize("answer", ["Yes, go ahead", "Sure, go ahead", "Yes, do it", "OK, sounds good", "Yes (Recommended)", "Yes, fix them all"])
def test_a_plain_yes_in_its_usual_words_lifts_the_hold(agent, answer):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    agent.load("occam:occam-python")
    agent.send("post-tool", tool_name="AskUserQuestion", tool_input={"answers": {"Should I fix them?": answer}})
    assert decision(agent.try_edit()) is None


def test_a_file_said_to_have_been_written_isnt_one_to_write(agent):
    (agent.project / "DESIGN.md").write_text("# design\n")
    agent.prompt("Review only. The design was written up in DESIGN.md; check the code against it.")
    agent.load()
    assert decision(agent.try_edit("DESIGN.md")) == "deny"


@pytest.mark.parametrize("question", ["Should I fix the bug where the token is not refreshed?", "Should I update the handler to return None instead of raising?",
                                      "Should I remove the dead code after the return statement?", "Shall I go ahead with the fixes?", "Should I fix the bugs listed in the review?",
                                      "Should I apply the fixes from the review?", "Should I fix the items on the checklist?", "Should I proceed with implementing the fixes?",
                                      "Should I fix the review findings?", "Should I fix the review comments?", "Should I fix the findings in the report?"])
def test_a_yes_to_a_question_about_the_code_lifts_the_hold_whatever_the_bug_is_called(agent, question):
    agent.prompt("Review only, don't change anything.")
    agent.load()
    agent.load("occam:occam-python")
    agent.send("post-tool", tool_name="AskUserQuestion", tool_input={"answers": {question: "Yes"}})
    assert decision(agent.try_edit()) is None


@pytest.mark.parametrize("prompt", ["Review only. Can you write the findings to REVIEW.md?", "Review only. Add the findings to `REVIEW.md`."])
def test_a_report_asked_for_politely_or_quoted_may_be_written_where_it_exists(agent, prompt):
    (agent.project / "REVIEW.md").write_text("# review\n")
    agent.prompt(prompt)
    agent.load()
    assert decision(agent.try_edit("REVIEW.md")) is None
    assert decision(agent.try_edit()) == "deny"


def test_continuing_with_the_plan_after_a_plan_only_turn_is_read_afresh(agent):
    agent.prompt("Plan only, don't change anything.")
    agent.load()
    agent.load("occam:occam-python")
    agent.stop("Here is the plan.")
    agent.prompt("Continue with the plan")  # after a plan, carrying on with it is usually building it
    assert decision(agent.try_edit()) is None


@pytest.mark.parametrize("prompt", ["Review only, but go ahead and write the findings to REVIEW.md.", "Review only. Go ahead and add your notes to REVIEW.md."])
def test_a_go_ahead_to_write_the_report_is_leave_for_the_report_only(agent, prompt):
    agent.prompt(prompt)
    agent.load()
    assert decision(agent.send("pre-tool", tool_name="Write", tool_input={"file_path": agent.path("REVIEW.md")})) is None
    assert decision(agent.try_edit()) == "deny"
