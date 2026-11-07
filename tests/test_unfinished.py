"""What the hook sees a run leave undone, and how it reads the shell commands that tell it so.

Commands and reports here are shaped like ones in saved runs. Most of these failed silently before: a multi-line commit message
hid the tests on the same line, and an edit made with `python3 -I - <<E` wasn't an edit at all, so Stop had nothing to compare.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from test_occam_hook import Agent, added, decision

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools.zero_tests import ran_no_tests  # noqa: E402

BIKESHARE = ROOT / "evals" / "cases" / "python" / "bikeshare-dock-usage" / "files" / "notebooks" / "q3_dock_usage.ipynb"
NO_CHECK = "No check has run since the last code edit"
STOPPED = "part of the request wasn't done"
CANT_RUN = "can't run top to bottom"


@pytest.fixture
def agent(tmp_path):
    made = Agent(tmp_path)
    made.prompt("Fix it")
    made.load()
    made.load("occam:occam-python")
    return made


def notebook(*cells):
    return json.dumps({"cells": [{"cell_type": "code", "source": [cell], "metadata": {}, "outputs": [], "execution_count": None} for cell in cells],
                       "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


# ------------------------------------------------------------ what a command really runs

@pytest.mark.parametrize("command", [
    'pytest -q && git commit -m "first line\nsecond line"',
    'python3 -m \\\n  pytest -q',
    "# don't skip this\npytest -q",
    'echo "unbalanced\npytest -q',
    "bash -c 'cd sub\npytest -q'",
])
def test_a_check_is_seen_however_the_command_is_laid_out(agent, command):
    agent.edit()
    agent.bash(command, output="3 passed")
    assert NO_CHECK not in added(agent.stop("Done."))


@pytest.mark.parametrize("command", [
    'rm -rf /Users/x/project && git commit -m "first line\nsecond line"',
    "rm -rf \\\n  /Users/x/project",
    'echo "unbalanced\nrm -rf /Users/x/project',
    "bash -c 'cd sub\nrm -rf /Users/x/project'",
])
def test_a_risky_command_is_seen_however_the_command_is_laid_out(agent, command):
    assert decision(agent.try_bash(command)) == "ask"


def test_a_comment_is_not_a_command(agent):
    assert decision(agent.try_bash("# clean up later; rm -rf /Users/x/project\nls")) is None


def test_a_quoted_message_is_not_a_command(agent):
    assert decision(agent.try_bash('git status && echo "before\nrm -rf /Users/x/project\nafter"')) is None


@pytest.mark.parametrize("command", [
    "python3 -I - <<'E'\np='app.py'\nopen(p,'w').write('x')\nE",
    "python3 -B - <<'E'\nimport pathlib\npathlib.Path('app.py').write_text('x')\nE",
    "python3 - <<'E'\nopen('app.py', mode='w').write('x')\nE",
    "python3 -c \"open('app.py','w').write('x')\"",
    "python3 -Ic \"open('app.py','wb').write(b'x')\"",
    "python3 - <<'E'\nimport os\nopen(os.path.join('src', 'app.py'), 'w').write('x')\nE",
])
def test_inline_python_that_writes_is_an_edit(agent, command):
    agent.bash(command)
    assert NO_CHECK in added(agent.stop("Done."))


@pytest.mark.parametrize("command", [
    "python3 - <<'E'\nprint(open('app.py').read())\nE",  # 'a' starts the file name here, and isn't a mode
    "python3 -c \"print(open('app.py', 'r').read())\"",
    "python3 -c \"open('/tmp/elsewhere/x.py','w').write('x')\"",
    "cat > $TMPDIR/gen.py <<'E'\nopen(out,'w').write('x')\nE",  # written out, and not run here
    "python3 -m pytest -c conf.ini",
    "cd $TMPDIR && cp old.py new.py && sed -i '' 's/a/b/' new.py",
])
def test_reading_or_working_elsewhere_is_not_an_edit(agent, command):
    agent.bash(command)
    assert agent.stop("Done.") is None


def test_inline_python_doesnt_check_its_own_edit_but_a_real_check_after_it_counts(agent):
    agent.bash("python3 -I - <<'E'\nopen('app.py','w').write('x')\nE\npytest -q", output="3 passed")
    assert NO_CHECK not in added(agent.stop("Done."))


def test_inline_python_that_only_reads_can_still_be_a_check(agent):
    agent.edit()
    agent.bash("python3 -c \"import app; assert app.f() == 1\"")
    assert NO_CHECK not in added(agent.stop("Done."))


def read_only(tmp_path):
    agent = Agent(tmp_path)
    (agent.project / "app.py").write_text("a = 1\n")
    agent.prompt("Review only, change nothing.")
    return agent


def test_a_read_only_turn_holds_inline_python_too(tmp_path):
    assert decision(read_only(tmp_path).try_bash("python3 -I - <<'E'\nopen('app.py','w').write('x')\nE")) == "deny"


@pytest.mark.parametrize("command", [
    "python3 scripts/occam.py golden record base rm -f app.py",
    "python3 scripts/occam.py golden record base -- rm -f app.py",
    "python3 scripts/occam.py golden record base --timeout 5 rm -f app.py",
])
def test_golden_is_judged_by_what_it_runs(tmp_path, command):
    assert decision(read_only(tmp_path).try_bash(command)) == "deny"


def test_bsd_sed_records_the_file_and_not_the_script(agent):
    agent.bash("sed -i '' 's/a/b/' app.py && sed -i '' 's/c/d/' other.py")
    agent.bash("git diff", output="diff")
    agent.bash("pytest -q", output="3 passed")
    assert agent.stop("Done.") is None


# ------------------------------------------------------------ a report admitting part of the request wasn't done

@pytest.mark.parametrize("report", [
    "I split out only a small part of `settlement.py`. The tests rely on the rest staying where it is.",
    "I split out only the two parts that could move without changing behavior.",
    "The rest of `settlement.py` has to stay put for now.",
    "**Going further**\nSplitting the rest would take some design work.",
    "I didn't move the rest, because tests patch those names.",
    "## Why I didn't split further\nPatched names.",
])
def test_stopping_short_is_challenged(agent, report):
    agent.edit()
    agent.bash("pytest -q", output="3 passed")
    text = added(agent.stop(report))
    assert STOPPED in text and "name the one decision" in text


@pytest.mark.parametrize("report", [
    "Fixed the bug, and the rest of the workbook stays readable.",
    "I only moved the helpers, as you asked.",
    "## What I didn't check\nThe linter isn't set up.",
    "**Things I noticed but didn't change:** the README is out of date.",
    "A redelivery picks up from the first step that isn't finished.",
    "It now uses `functools.partial`, so each site keeps its own offset.",
    "The fix is in. If you want it recorded for an operator, I can add that.",
])
def test_ordinary_reports_are_left_alone(agent, report):
    agent.edit()
    agent.bash("pytest -q", output="3 passed")
    assert STOPPED not in added(agent.stop(report))


def test_stopping_short_is_challenged_once(agent):
    report = "I split out only a small part."
    agent.edit()
    agent.bash("pytest -q", output="3 passed")
    assert STOPPED in added(agent.stop(report))
    agent.edit()
    agent.bash("pytest -q", output="3 passed")
    assert STOPPED not in added(agent.stop(report))


def test_nothing_is_challenged_without_an_edit(agent):
    assert agent.stop("I split out only a small part.") is None


# ------------------------------------------------------------ a changed notebook that can't run

def test_a_changed_notebook_that_cant_run_is_sent_back(agent):
    Path(agent.path("n.ipynb")).write_text(notebook("print(TOTAL)", "TOTAL = 1"))
    agent.edit("n.ipynb")
    agent.bash("pytest -q", output="3 passed")
    text = added(agent.stop("Fixed the formula."))
    assert CANT_RUN in text and "TOTAL" in text and "n.ipynb" in text


def test_a_notebook_edited_from_inline_python_counts(agent):
    Path(agent.path("n.ipynb")).write_text(notebook("print(TOTAL)", "TOTAL = 1"))
    agent.bash("python3 -I - <<'E'\np='n.ipynb'\nt=open(p).read()\nopen(p,'w').write(t)\nE")
    assert CANT_RUN in added(agent.stop("Fixed the formula."))


def test_a_notebook_in_working_order_is_left_alone(agent):
    Path(agent.path("n.ipynb")).write_text(notebook("TOTAL = 1", "print(TOTAL)"))
    agent.edit("n.ipynb")
    agent.bash("pytest -q", output="3 passed")
    assert CANT_RUN not in added(agent.stop("Fixed the formula."))


def test_a_notebook_not_changed_here_is_left_alone(agent):
    Path(agent.path("n.ipynb")).write_text(notebook("print(TOTAL)", "TOTAL = 1"))
    agent.edit()
    agent.bash("pytest -q", output="3 passed")
    assert CANT_RUN not in added(agent.stop("Fixed the formula."))


def test_an_unreadable_notebook_fails_open(agent):
    Path(agent.path("n.ipynb")).write_text("{not json")
    agent.edit("n.ipynb")
    agent.bash("pytest -q", output="3 passed")
    assert CANT_RUN not in added(agent.stop("Fixed it."))


def test_the_notebook_note_is_sent_once(agent):
    Path(agent.path("n.ipynb")).write_text(notebook("print(TOTAL)", "TOTAL = 1"))
    agent.edit("n.ipynb")
    agent.bash("pytest -q", output="3 passed")
    assert CANT_RUN in added(agent.stop("Fixed."))
    agent.edit("n.ipynb")
    agent.bash("pytest -q", output="3 passed")
    assert CANT_RUN not in added(agent.stop("Fixed."))


def test_the_notebook_all_those_runs_left_broken_is_caught(agent):
    Path(agent.path("q3.ipynb")).write_bytes(BIKESHARE.read_bytes())
    agent.edit("q3.ipynb")
    agent.bash("pytest -q", output="3 passed")
    assert "REPORT_START" in added(agent.stop("Rides per dock-day is 0.287."))


# ------------------------------------------------------------ a run that ran no tests

@pytest.mark.parametrize("output", [
    "collected 0 items",
    "=== no tests ran in 0.01s ===",
    "=== 3 deselected in 0.01s ===",
    "=== 3 skipped in 0.01s ===",
    "Ran 0 tests in 0.000s\n\nOK",
    "Ran 2 tests in 0.000s\n\nOK (skipped=2)",
    "No tests found, exiting with code 0",  # jest --passWithNoTests
    "No test files found, exiting with code 0",  # vitest
    "No tests were found!!!",  # ctest
    "No tests executed!",  # phpunit
    "0 examples, 0 failures",  # rspec
    "  0 passing (2ms)",  # mocha
    "running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out",  # cargo
    "?   \texample.com/a\t[no test files]",  # go
    "ok  \texample.com/a\t0.002s [no tests to run]",
])
def test_nothing_ran(output):
    assert ran_no_tests(output)


@pytest.mark.parametrize("output", [
    "=== 3 passed in 0.01s ===",
    "=== 3 passed, 2 deselected in 0.01s ===",
    "=== 3 passed, 2 skipped in 0.01s ===",
    "Ran 3 tests in 0.000s\n\nOK",
    "Ran 3 tests in 0.000s\n\nOK (skipped=1)",
    "  10 passing (2ms)",
    "12 examples, 0 failures",
    "running 0 tests\ntest result: ok. 0 passed; 0 failed; 0 ignored\nrunning 4 tests\ntest result: ok. 4 passed; 0 failed; 0 ignored",
    "?   \texample.com/a\t[no test files]\nok  \texample.com/b\t0.002s",
    "?   \texample.com/a\t[no test files]\n--- FAIL: TestB (0.00s)\nFAIL\texample.com/b\t0.002s",
])
def test_something_ran(output):
    assert not ran_no_tests(output)


def test_the_hook_and_the_tools_agree_on_go(agent):
    agent.edit()
    agent.bash("go test ./...", output="?   \texample.com/a\t[no test files]")
    assert "no check passed" in added(agent.stop("Tests pass."))


# ------------------------------------------------------------ failures that say nothing about this code

@pytest.mark.parametrize("command", [
    'd=$(mktemp -d) && git show HEAD:app.py > "$d/app.py" && cd "$d" && pytest -q',
    "cd $TMPDIR/oldcode && pytest -q",
])
def test_a_new_test_failing_on_a_copy_of_the_old_code_is_not_a_failure_here(agent, command):
    agent.edit()
    agent.bash("pytest -q", output="3 passed")
    agent.bash(command, output="1 failed, 2 passed in 0.01s")
    assert "hasn't passed since" not in added(agent.stop("All tests pass, and the new test fails on the old code."))


def test_a_command_that_never_started_is_not_a_failure_here(agent):
    agent.edit()
    agent.send("post-failure", tool_name="Bash", tool_input={"command": "python -m pytest tests/a.py"}, error="Exit code 127\ncommand not found: python")
    agent.bash("python3 -m pytest -q", output="3 passed")
    assert "hasn't passed since" not in added(agent.stop("All tests pass."))


def test_a_real_failure_after_a_copy_run_still_counts(agent):
    agent.edit()
    agent.bash("cd $TMPDIR/oldcode && pytest -q", output="1 failed in 0.01s")
    agent.bash("pytest -q | tail -1", output="1 failed in 0.01s")
    assert "hasn't passed since" in added(agent.stop("All done."))


def test_a_scoped_claim_beside_an_honest_failure_is_fine(agent):
    agent.edit()
    agent.bash("pytest -q | tail -1", output="1 failed, 9 passed in 0.01s")
    report = "I fixed the bug, and all the pricing tests pass.\nThe full suite is not green, because one tax test fails."
    assert "hasn't passed since" not in added(agent.stop(report))


def test_an_unscoped_claim_beside_a_mention_of_failure_is_still_challenged(agent):
    agent.edit()
    agent.bash("pytest -q | tail -1", output="1 failed, 9 passed in 0.01s")
    assert "hasn't passed since" in added(agent.stop("All tests pass.\nThere was a failure earlier."))


def test_a_copy_run_failing_doesnt_make_the_next_test_edit_look_like_a_cover_up(agent):
    agent.bash("cd $TMPDIR/oldcode && pytest -q", output="1 failed in 0.01s")
    old, new = "def test_a():\n    assert f(1) == 1\n", "def test_a():\n    assert f(1) == 1\n\n# noqa\n"
    (agent.project / "test_x.py").write_text(old)
    output = agent.send("pre-tool", tool_name="Edit", tool_input={"file_path": agent.path("test_x.py"), "old_string": old, "new_string": new})
    assert decision(output) != "deny"


def test_a_temp_copy_reached_through_a_variable_is_not_the_project(agent):
    agent.bash("W=$TMPDIR/fq && mkdir -p $W && cd $W && python3 - <<'E'\nopen('bad.json','w').write('x')\nE")
    assert agent.stop("Done.") is None


def test_a_notebook_edited_after_an_earlier_cd_is_still_found(agent):
    folder = agent.project / "notebooks"
    folder.mkdir()
    (folder / "n.ipynb").write_text(notebook("print(TOTAL)", "TOTAL = 1"))
    agent.send("post-tool", tool_name="Bash", cwd=str(folder), tool_response={"stdout": ""},
               tool_input={"command": "python3 -I - <<'E'\np='n.ipynb'\nt=open(p).read()\nopen(p,'w').write(t)\nE"})
    assert CANT_RUN in added(agent.stop("Fixed the formula."))


def test_runs_on_a_copy_dont_build_a_failing_streak(agent):
    agent.edit()
    for _ in range(3):
        output = agent.bash("cd $TMPDIR/oldcode && pytest -q", output="1 failed in 0.01s")
    assert "in a row have failed" not in added(output)


def git(project, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=project, check=True, capture_output=True)


def test_an_edit_script_with_an_unreadable_target_still_gets_its_files_scanned(agent):
    (agent.project / "n.ipynb").write_text(notebook("TOTAL = 1", "print(TOTAL)"))
    git(agent.project, "init", "-q")
    git(agent.project, "add", "-A")
    git(agent.project, "commit", "-qm", "start")
    (agent.project / "n.ipynb").write_text(notebook("print(TOTAL)", "TOTAL = 1"))
    agent.bash("python3 - <<'E'\nimport sys\nopen(sys.argv[1],'w').write('x')\nE")
    assert CANT_RUN in added(agent.stop("Fixed the formula."))


def test_no_git_and_an_unreadable_target_fails_open(agent):
    agent.bash("python3 - <<'E'\nimport sys\nopen(sys.argv[1],'w').write('x')\nE")
    assert CANT_RUN not in added(agent.stop("Fixed the formula."))
