"""The enforcement hook's handling of the Python ecosystem: runners, formatters, test output, file types and file size."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_occam_hook import ROOT, Agent, added, decision


@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path)


DRY_RUNS = ["black --check .", "black --diff .", "isort --check-only .", "isort -c .", "ruff format --check .", "ruff format --diff .",
            "python -m black --check .", "uv run black --check .", "uv run ruff format --check .", "nbstripout --is-stripped n.ipynb"]


@pytest.mark.parametrize("command", DRY_RUNS)
def test_a_dry_run_formatter_is_allowed_on_a_read_only_turn(agent, command):
    agent.prompt("Review only, don't change anything.")
    assert decision(agent.try_bash(command)) is None


@pytest.mark.parametrize("command", DRY_RUNS)
def test_a_dry_run_formatter_after_a_real_check_is_not_an_edit(agent, command):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash("pytest -q", output="1 passed in 0.1s")
    agent.bash(command, output="All done")
    assert "No check has run" not in added(agent.stop())


@pytest.mark.parametrize("command", DRY_RUNS)
def test_a_formatting_pass_alone_says_nothing_about_behavior(agent, command):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash(command, output="All done")
    assert "No check has run" in added(agent.stop())


@pytest.mark.parametrize("command", [
    "black .", "isort .", "python -m black .", "python3 -m isort src", "uv run black .", "poetry run isort .",
    "python -m ruff format .", "uv run ruff check --fix .", "uvx black .", "uvx --from black black .", "conda run -n dev black .",
    "pipx run black .", "uv run --with black black .", "autopep8 -i a.py", "autoflake --in-place a.py", "yapf -i a.py", "yapf -ir .",
    "pyupgrade a.py", "uv lock", "uv sync", "poetry lock", "pdm lock", "pipenv lock", "pip-compile requirements.in", "nbstripout nb.ipynb",
    "jupyter nbconvert --to notebook --execute --inplace nb.ipynb", "jupyter nbconvert --execute --to notebook nb.ipynb",
    "uv run python -m black .", "python -B -m black .", "python -X dev -m black .", "uvx black@latest .", "uv run --package api black .",
    "uv --directory api run black .", "pre-commit run --all-files", "nbqa black nb.ipynb", "ruff check --fix-only .",
    "ruff check --add-noqa .", "ruff --isolated format .", "ruff --config x.toml format .", "uv pip compile -o r.txt r.in",
    "uv pip compile r.in --output-file=r.txt", "uv add --frozen six", "uv sync --locked",
    "uv run -n black .", "python -Bm black .", "uvx black==26.10.1 .", "uv tool run black .", "python -m piptools compile",
    "uv run -w six black .", "poetry -C api run black .", "hatch -e dev run black .", "timeout 60 black .", "nice -n 10 black .",
    "jupyter nbconvert --inplace --output-dir /tmp/x nb.ipynb", "jupyter nbconvert --output-dir . nb.ipynb",
    "poetry -C api lock", "poetry -C api add six", "hatch --env dev run black .",
])
def test_rewriting_files_through_any_runner_is_held_on_a_read_only_turn(agent, command):
    agent.prompt("Review only, don't change anything.")
    assert decision(agent.try_bash(command)) == "deny"


@pytest.mark.parametrize("command,output", [("papermill in.ipynb out.ipynb", "out.ipynb"), ("jupyter nbconvert --output-dir=docs nb.ipynb", "docs")])
def test_a_runners_named_output_is_held_on_a_read_only_turn_only_once_it_exists(agent, command, output):
    agent.prompt("Review only, don't change anything.")
    assert decision(agent.try_bash(command)) is None
    (agent.project / output).write_text("x")
    assert decision(agent.try_bash(command)) == "deny"


@pytest.mark.parametrize("command", [
    "uv run black --version", "uvx black --help", "pip-compile --help", "uv lock --check", "uv lock --locked", "uv sync --dry-run",
    "black -h", "isort -V", 'jupyter nbconvert --output-dir="/tmp/x" nb.ipynb', "jupyter nbconvert --output-dir ~/out nb.ipynb",
    "jupyter nbconvert -h", "ruff check format", "ruff format -", "nbqa black nb.ipynb --nbqa-diff",
    'jupyter nbconvert --to notebook --execute --output-dir "$(mktemp -d)" analysis.ipynb',
    "jupyter nbconvert --execute --stdout nb.ipynb", "jupyter nbconvert --execute --output-dir /tmp/out nb.ipynb",
    "nbqa ruff nb.ipynb", "nbqa black --check nb.ipynb", "ruff check .", "pytest --collect-only -q", "cargo fmt --check",
])
def test_commands_that_write_nothing_are_allowed_on_a_read_only_turn(agent, command):
    agent.prompt("Review only, don't change anything.")
    assert decision(agent.try_bash(command)) is None


@pytest.mark.parametrize("command", [
    "coverage run -m pytest", "python -m coverage run -m pytest", "pre-commit run --all-files", "hatch test",
    "conda run -n dev pytest", "uvx ruff check .", "pipx run ruff check .", "uv run --python 3.12 pytest", "ty check",
    "bandit -r src", "pip-audit", "vulture src", "lint-imports", "sphinx-build -W docs out", "mkdocs build --strict",
    "nbqa ruff nb.ipynb", "jupyter nbconvert --to notebook --execute --output-dir out nb.ipynb", "jupyter execute nb.ipynb",
    "papermill in.ipynb out.ipynb", "python -m unittest", "python -m pytest", "python -B -m pytest", "python manage.py test",
    "uv run python -m pytest", "uv run python script.py", "ruff check --fix .", "python cli.py --help", "./cli --help",
    "timeout 60 python -m pytest", "timeout 5m pytest -q", "nice -n 10 pytest", "pants test ::", "tach check", "mutmut run",
    "psql -h localhost -c 'select 1'",
])
def test_python_checks_are_recognized(agent, command):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash(command, output="ok")
    assert "No check has run" not in added(agent.stop())


@pytest.mark.parametrize("command", [
    "python -m venv .venv", "python -m pip install x", "uv run pip install x", "uv run python -m pip install x", "pre-commit install",
    "coverage erase", "mkdocs serve", "hatch shell", "black .", "python -m black .", "uv run isort .", "ruff format .",
    "pytest --version", "pytest --collect-only -q", "python --version", "uv run python --version", "uvx ruff --help",
    "uv run echo hi", "ruff rule F401", "pytest --markers", "command -v pytest", "ruff format -", "ruff format --check .",
])
def test_setup_formatting_and_information_are_not_checks(agent, command):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash(command, output="ok")
    assert "No check has run" in added(agent.stop())


@pytest.mark.parametrize("output", [
    "FAILED t.py::x\n2 failed, 3 passed in 0.12s",
    "==== 1 failed in 0.1s ====",
    "==== 1 passed, 2 errors in 0.1s ====",
    "Ran 5 tests in 0.1s\n\nFAILED (failures=1)",
    "Ran 0 tests in 0.000s\n\nOK",
    "----\n\nRan 0 tests in 0.000s\n\nOK",
    "2 deselected in 0.00s",
    "==== 3 deselected in 0.01s ====",
    "3 skipped in 0.01s",
    "1 skipped, 1 deselected in 0.00s",
    "Found 3 errors in 1 file (checked 2 source files)",
    "Ran 2 tests in 0.0s\n\nOK (skipped=2)",
    "Ran 2 tests in 0.0s\n\nFAILED (unexpected successes=1)",
    "3 errors, 0 warnings, 0 informations",
    "Found 3 diagnostics",
    "\x1b[31m1 failed\x1b[0m, \x1b[32m3 passed\x1b[0m in 0.1s",
    "ImportError while loading conftest '/x/conftest.py'.",
    "ERROR: file or directory not found: nope",
    "ERROR tests/test_a.py - ImportError: no module",
    "ERROR test_a.py::test_x[a b]",
    "a.py:1:1: E501 line too long",
    "a.py:3:0: C0114: Missing module docstring (missing-module-docstring)",
    "py312: FAIL code 1 (0.10 seconds)\n  evaluation failed :( (0.20 seconds)",
    "Traceback (most recent call last):\n  File \"a.py\", line 1, in <module>\n    boom()\nValueError: nope\n",
])
def test_a_pass_claim_is_challenged_when_the_output_shows_no_pass(agent, output):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash("pytest -q | tail -3", output=output)
    assert "no check passed" in added(agent.stop("All tests pass."))


@pytest.mark.parametrize("output", [
    "5 passed in 0.1s", "==== 5 passed, 2 skipped in 0.1s ====", "5 passed, 1 deselected in 0.1s", "0 errors in 0.1s",
    "Ran 5 tests in 0.1s\n\nOK", "Ran 5 tests in 0.1s\n\nOK (skipped=2)", "Success: no issues found in 3 source files", "All checks passed!",
    "Found 2 errors (2 fixed, 0 remaining).", "0 errors, 0 warnings, 0 informations",
    "FAILED login attempt for bob\n5 passed in 0.1s", "ERROR app.py:3 boom\n5 passed in 0.1s", "ERROR: could not reach the mock\n5 passed in 0.1s",
    "Traceback (most recent call last):\n  File \"a.py\", line 1, in <module>\nValueError: logged and handled\n5 passed in 0.1s",
])
def test_a_pass_claim_stands_when_the_output_shows_a_pass(agent, output):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash("pytest -q | tail -3", output=output)
    assert not added(agent.stop("All tests pass."))


SOURCES = {
    "failing": "def test_a():\n    assert False\n\ndef test_b():\n    assert True\n",
    "skipped": "import pytest\n\n@pytest.mark.skip(reason='x')\ndef test_a():\n    assert False\n",
    "passing": "import pytest\n\ndef test_a():\n    assert True\n\n@pytest.mark.skip(reason='x')\ndef test_b():\n    assert False\n",
}


def real_pytest(tmp_path, kind, *args, **env):
    folder = tmp_path / "real"
    folder.mkdir()
    (folder / "test_real.py").write_text(SOURCES[kind])
    done = subprocess.run([sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", *args], cwd=folder, capture_output=True,
                          text=True, timeout=60, env={**os.environ, **env})
    return done.stdout


@pytest.mark.parametrize("kind, args, env", [
    ("failing", [], {}), ("failing", ["-q"], {}), ("failing", ["-qq"], {}), ("failing", ["--color=yes"], {}),
    ("failing", ["-q", "--color=yes"], {}), ("failing", [], {"PY_COLORS": "1"}), ("failing", [], {"FORCE_COLOR": "1"}),
    ("skipped", [], {}), ("skipped", ["-q"], {}), ("skipped", ["--color=yes"], {}),
    ("failing", ["-k", "nomatch"], {}), ("failing", ["-q", "-k", "nomatch"], {}), ("failing", ["--color=yes", "-k", "nomatch"], {}),
])
def test_real_pytest_output_behind_a_pipe_is_not_a_pass(agent, tmp_path, kind, args, env):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash("pytest | tail -3", output=real_pytest(tmp_path, kind, *args, **env))
    assert "no check passed" in added(agent.stop("All tests pass."))


@pytest.mark.parametrize("args", [["--no-such-flag"], ["nope/"]])
def test_real_pytest_that_could_not_start_is_not_a_pass(agent, tmp_path, args):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    folder = tmp_path / "real"
    folder.mkdir()
    done = subprocess.run([sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", *args], cwd=folder, capture_output=True, text=True, timeout=60)
    agent.bash("pytest 2>&1 | tail -3", output=done.stdout + done.stderr)
    assert "no check passed" in added(agent.stop("All tests pass."))


def test_real_pytest_with_a_broken_conftest_is_not_a_pass(agent, tmp_path):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    (tmp_path / "conftest.py").write_text("import no_such_module_here\n")
    done = subprocess.run([sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    agent.bash("pytest 2>&1 | tail -3", output=done.stdout + done.stderr)
    assert "no check passed" in added(agent.stop("All tests pass."))


def test_a_real_script_that_died_is_not_a_pass(agent, tmp_path):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    script = tmp_path / "boom.py"
    script.write_text("raise ValueError('nope')\n")
    done = subprocess.run([sys.executable, "-B", str(script)], capture_output=True, text=True, timeout=60)
    agent.bash("python boom.py 2>&1 | tail -3", output=done.stderr)
    assert "no check passed" in added(agent.stop("The tests pass."))


@pytest.mark.parametrize("shape", [lambda text: {"output": {"stdout": text}}, lambda text: [text], lambda text: text])
def test_failures_are_found_in_any_response_shape(agent, shape):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.send("post-tool", tool_name="Bash", tool_input={"command": "pytest | tail -1"}, tool_response=shape("FAILED t.py::x\n"))
    assert "no check passed" in added(agent.stop("All tests pass."))


@pytest.mark.parametrize("args", [[], ["-q"], ["-qq"], ["--color=yes"]])
def test_real_passing_pytest_output_with_a_printed_failed_line_is_a_pass(agent, tmp_path, args):
    folder = tmp_path / "real"
    folder.mkdir()
    (folder / "test_real.py").write_text("def test_a():\n    print('FAILED login attempt')\n    print('ERROR app.py:3 boom')\n")
    done = subprocess.run([sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-s", *args], cwd=folder, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash("pytest -s | tail -3", output=done.stdout)
    assert not added(agent.stop("All tests pass."))


@pytest.mark.parametrize("args", [[], ["-q"], ["-qq"], ["--color=yes"]])
def test_real_passing_pytest_output_is_a_pass(agent, tmp_path, args):
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash("pytest | tail -3", output=real_pytest(tmp_path, "passing", *args))
    assert not added(agent.stop("All tests pass."))


@pytest.mark.parametrize("source", [
    "import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail()\n",
    "import unittest\n\nclass T(unittest.TestCase):\n    @unittest.skip('x')\n    def test_a(self):\n        self.fail()\n",
])
def test_real_unittest_output_behind_a_pipe_is_not_a_pass(agent, tmp_path, source):
    (tmp_path / "test_real.py").write_text(source)
    done = subprocess.run([sys.executable, "-B", "-m", "unittest"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    agent.prompt("Fix it")
    agent.load()
    agent.edit()
    agent.bash("python -m unittest 2>&1 | tail -3", output=done.stderr)
    assert "no check passed" in added(agent.stop("All tests pass."))


@pytest.mark.parametrize("name", ["n.ipynb", "fast.pyx", "fast.pxd", "gui.pyw", "stubs/a.pyi"])
def test_every_python_file_type_gets_the_language_skill(agent, name):
    agent.prompt("Fix it")
    agent.load()
    assert "occam-python" in added(agent.try_edit(name))


def test_a_notebook_cell_with_risky_semantics_mentions_the_language_skill(agent):
    agent.prompt("Fix the cell")
    agent.load()
    output = agent.send("pre-tool", tool_name="NotebookEdit",
                        tool_input={"notebook_path": agent.path("n.ipynb"), "new_source": "await asyncio.gather(*tasks)"})
    assert decision(output) is None and "occam-python" in added(output)


@pytest.mark.parametrize("request_text", ["Fix the circular imports in app", "Split this module in two", "Split up this module", "Keep this notebook working"])
def test_structural_python_work_mentions_the_language_skill(agent, request_text):
    agent.prompt(request_text)
    agent.load()
    output = agent.try_edit()
    assert decision(output) is None and "occam-python" in added(output)


def test_an_audit_request_stays_read_only(agent):
    agent.prompt("Audit this module")
    agent.load()
    assert decision(agent.try_edit()) == "deny"


@pytest.mark.parametrize("written", ['eval("x")', 'exec("x")', "round(1.5)", "subprocess.run(c, shell=True)", "shell=True", "mock.patch('a.b')", "os.system(c)", "tarfile.open(p)"])
def test_risky_python_in_the_edit_itself_mentions_the_language_skill(agent, written):
    agent.prompt("Fix it")
    agent.load()
    output = agent.send("pre-tool", tool_name="Edit", tool_input={"file_path": agent.path("a.py"), "new_string": written})
    assert decision(output) is None and "occam-python" in added(output)


@pytest.mark.parametrize("name", ["requirements/dev.txt", "requirements/base.in", "requirements.in", "constraints.txt",
                                  "constraints-dev.txt", "environment.yml", "environment.yaml", "pyproject.toml"])
def test_python_dependency_files_state_the_design_facts(agent, name):
    agent.prompt("Bump it")
    agent.load()
    output = agent.try_edit(name)
    assert decision(output) is None and "the package the documentation means" in added(output)


@pytest.mark.parametrize("name", ["notes/requirements.md", "docs/constraints.md", "docs/environment.md", "data/requirements_old.csv"])
def test_documents_named_like_dependency_files_are_not_held(agent, name):
    agent.prompt("Update it")
    agent.load()
    assert decision(agent.try_edit(name)) is None


@pytest.mark.parametrize("name", ["conftest.py", "src/pkg/conftest.py"])
def test_conftest_counts_as_a_test_file(agent, name):
    agent.prompt("Fix it")
    agent.load()
    assert "tests that can fail" in added(agent.try_edit(name))


def write_lines(agent, name, count, head=""):
    path = Path(agent.path(name))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + "x = 1\n" * count)


def test_an_edit_leaving_a_python_file_very_large_is_mentioned_once_and_nothing_is_held(agent):
    write_lines(agent, "big.py", 1001)
    note = added(agent.edit("big.py"))
    assert "big.py is 1001 lines" in note and "separate change" in note and "takes precedence" in note
    assert (ROOT / "plugin/skills/occam-python/references/structure.md").as_posix() in note
    assert not added(agent.edit("big.py")), "once per file per session"
    agent.prompt("Fix it")
    agent.load()
    assert decision(agent.try_edit("big.py")) is None, "a size note holds nothing"


def test_the_size_note_comes_before_the_edit_of_a_file_already_large(agent):
    write_lines(agent, "big.py", 1500)
    agent.prompt("Add a report")
    agent.load()
    held = agent.try_edit("big.py")
    assert decision(held) is None and "big.py is 1500 lines" in added(held) and "its own module" in added(held)
    assert "big.py is" not in added(agent.edit("big.py")), "already said, so not again after the edit"


def test_a_small_file_gets_no_size_note_before_the_edit(agent):
    write_lines(agent, "small.py", 20)
    agent.prompt("Add a report")
    agent.load()
    assert "lines," not in added(agent.try_edit("small.py"))


@pytest.mark.parametrize("name", ["pkg/calendar.py", "pkg/random.py", "logging.py", "app/types.py"])
def test_a_new_module_named_after_the_standard_library_is_mentioned_and_not_held(agent, name):
    agent.prompt("Add it")
    agent.load()
    output = agent.try_edit(name)
    assert decision(output) is None and "standard library" in added(output)


@pytest.mark.parametrize("name", ["pkg/tidetable.py", "pkg/__init__.py", "pkg/calendar.txt", "pkg/calendar.go"])
def test_other_new_files_get_no_standard_library_note(agent, name):
    agent.prompt("Add it")
    agent.load()
    assert "standard library" not in added(agent.try_edit(name))


def test_an_existing_module_with_a_standard_library_name_gets_no_note(agent):
    write_lines(agent, "pkg/calendar.py", 5)
    agent.prompt("Fix it")
    agent.load()
    assert "standard library" not in added(agent.try_edit("pkg/calendar.py"))


def test_a_notebook_edit_points_directly_at_the_notebook_guidance_once(agent):
    agent.prompt("Fix the cell")
    agent.load()
    first = added(agent.try_edit("n.ipynb"))
    assert (ROOT / "plugin/skills/occam-python/references/notebooks.md").as_posix() in first
    assert "notebooks.md" not in added(agent.try_edit("n.ipynb"))


def test_a_python_test_edit_points_directly_at_the_testing_guidance_once(agent):
    agent.prompt("Fix it")
    agent.load()
    first = added(agent.try_edit("tests/test_a.py"))
    assert (ROOT / "plugin/skills/occam-python/references/testing.md").as_posix() in first
    assert "references/testing.md" not in added(agent.try_edit("tests/test_b.py"))


def test_a_test_edit_in_another_language_gets_no_python_pointer(agent):
    agent.prompt("Fix it")
    agent.load()
    assert "occam-python" not in added(agent.try_edit("tests/a_test.go"))


def test_a_python_audit_prompt_points_directly_at_the_audit_guidance(agent):
    Path(agent.path("pyproject.toml")).write_text("")
    assert (ROOT / "plugin/skills/occam-python/references/auditing.md").as_posix() in added(agent.prompt("Audit this repo"))


def test_a_python_review_prompt_gets_no_audit_path(agent):
    assert "references/auditing.md" not in added(agent.prompt("Review this Python pull request"))


def test_a_file_at_the_limit_is_not_mentioned(agent):
    write_lines(agent, "ok.py", 1000)
    assert not added(agent.edit("ok.py"))


def test_large_files_in_other_languages_are_mentioned_without_the_python_pointer(agent):
    write_lines(agent, "big.go", 2000)
    note = added(agent.edit("big.go"))
    assert "big.go is 2000 lines" in note and "occam-python" not in note


@pytest.mark.parametrize("name", ["big.ipynb", "schema.sql", "big.md", "big.json"])
def test_files_not_measured_in_lines_are_not_mentioned(agent, name):
    write_lines(agent, name, 5000)
    agent.prompt("Fix it")
    agent.load()
    agent.try_edit(name)  # real sessions send this first, and it gives the scanner its baseline
    assert "lines, past" not in added(agent.edit(name)), "other notes may fire here, such as the one for documentation"


@pytest.mark.parametrize("head", ["# @generated\n", "# Code generated by protoc. DO NOT EDIT.\n", "# Generated by a tool\n",
                                  "# Autogenerated file. Do not edit.\n", "# This file is generated. Do not edit.\n"])
def test_generated_files_are_not_mentioned(agent, head):
    write_lines(agent, "pb2.py", 5000, head=head)
    assert not added(agent.edit("pb2.py"))


def test_a_docstring_mentioning_generation_does_not_silence_the_note(agent):
    write_lines(agent, "tokens.py", 1500, head='"""Parse the tokens generated by the lexer."""\n')
    assert "tokens.py is" in added(agent.edit("tokens.py"))


def test_a_handwritten_note_not_to_edit_does_not_silence_the_note(agent):
    write_lines(agent, "careful.py", 1500, head="# Do not edit this without asking the billing team.\n")
    assert "careful.py is" in added(agent.edit("careful.py"))


def test_the_size_check_tolerates_a_file_that_is_gone(agent):
    assert not added(agent.edit("deleted.py"))


@pytest.mark.parametrize("request_text", ["Review this pull request in app.py", "Audit our Python code", "Review only: is the pytest suite sound?"])
def test_a_python_review_hears_about_the_language_skill(agent, request_text):
    assert "occam-python" in added(agent.prompt(request_text))


@pytest.mark.parametrize("marker", ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"])
def test_an_audit_prompt_in_a_python_project_hears_about_the_language_skill(agent, marker):
    Path(agent.path(marker)).write_text("")
    assert "occam-python" in added(agent.prompt("Audit this repo"))


def test_an_audit_prompt_from_a_subdirectory_of_a_python_project_hears_about_the_language_skill(agent):
    Path(agent.path("pyproject.toml")).write_text("")
    below = Path(agent.path("src"))
    below.mkdir()
    assert "occam-python" in added(agent.send("user-prompt", prompt="Audit this repo", cwd=str(below)))


def test_an_audit_prompt_elsewhere_gets_no_python_pointer(agent):
    assert "occam-python" not in added(agent.prompt("Audit this repo"))


def test_a_loaded_language_skill_and_non_python_reviews_get_no_pointer(agent):
    assert "occam-python" not in added(agent.prompt("Review this pull request in main.go"))
    agent.load("occam:occam-python")
    assert "occam-python" not in added(agent.prompt("Review this Python pull request"))


def test_ordinary_python_requests_get_no_pointer(agent):
    assert "occam-python" not in added(agent.prompt("Fix the python script"))


@pytest.mark.parametrize("words", [["uv"] + ["-x"] * 40_000 + ["run", "pytest"], ["python3"] + ["-q"] * 40_000 + ["-m", "pytest"], ["pytest"] + ["-git"] * 40_000])
def test_a_command_with_tens_of_thousands_of_options_is_classified_quickly(words):
    sys.path.insert(0, str(ROOT / "plugin" / "hooks"))
    import occam_commands
    started = time.monotonic()
    name, _ = occam_commands.run_by(words)
    occam_commands.is_check(words)
    occam_commands.writes_project_files(name, words[1:])
    assert time.monotonic() - started < 1, "a rebuilt list per option makes this quadratic"
    assert name == "pytest"
