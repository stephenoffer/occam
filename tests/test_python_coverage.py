"""occam-python covers each aspect of Python work, and what it states about Python and its tools stays true.

The traps below are executed, not just mentioned, so guidance can't quietly drift from what the interpreter does.
"""

import ast
import asyncio
import collections
import concurrent.futures
import datetime
import json
import os.path
import re
import shutil
import subprocess
import sys
import threading
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

import pytest
import yaml

from test_package import HOST_SPECIFIC, parts

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugin" / "skills" / "occam-python"
REFERENCES = sorted((SKILL / "references").glob("*.md"))
HOOK = ROOT / "plugin" / "hooks" / "occam_hook.py"

# Each aspect the skill claims, where it lives, and phrases whose loss would mean the coverage is gone.
ASPECTS = {
    "auditing": ("auditing", ["occam-audit", "read-only", "Configuration that hides problems", "--collect-only", "pip-audit"]),
    "structure": ("structure", ["`__init__.py`", "circular import", "`src/` layout", "`Protocol`", "`super().__init__()`"]),
    "naming": ("naming-and-docs", ["`snake_case`", "`_v2`", "public rename", "Put units in the name"]),
    "docs": ("naming-and-docs", ["PEP 257", "doctest", "Match the format already in use"]),
    "comments": ("naming-and-docs", ["why, not what", "Commented-out code", "Edit narration"]),
    "suppressions": ("naming-and-docs", ["`# noqa: S603`", "`# type: ignore[arg-type]`", "Say why"]),
    "file size": ("structure", ["Size limits", "`max-module-lines`", "Cut at a seam", "Splitting a module safely"]),
    "large codebases": ("structure", ["Large codebases", "Types as contracts", "Process model", "Monorepos"]),
    "testing": ("testing", ["Tests that never run", "Assertions that can't fail", "Patch where the name is looked up", "`autospec=True`", "Replacing working code"]),
    "moved apis": ("apis-and-security", ["`datetime.utcnow()`", "`pkg_resources`", "`@field_validator`", "`openai.ChatCompletion.create()`"]),
    "security sinks": ("apis-and-security", ["`yaml.safe_load`", "`shell=True`", "`hmac.compare_digest`", "`filter=\"data\"`"]),
    "notebooks": ("notebooks", ["Hidden state", "fresh kernel", "`execution_count`", "Unpinned installs"]),
    "runtime": ("runtime", ["`ExceptionGroup`", "`asyncio.to_thread`", "`check=True`", "`dropna=False`", "`validate=", "mypy.stubtest"]),
}


def reference_ids(path: Path) -> str:
    return path.stem


@pytest.mark.parametrize("aspect", ASPECTS)
def test_each_aspect_has_its_guidance(aspect):
    name, phrases = ASPECTS[aspect]
    text = (SKILL / "references" / f"{name}.md").read_text()
    missing = [phrase for phrase in phrases if phrase not in text]
    assert not missing, f"{aspect} lost {missing}"


def test_skill_links_every_reference_and_each_link_resolves():
    _, body = parts(SKILL / "SKILL.md")
    linked = set(re.findall(r"\]\((references/[^)#]+)", body))
    assert linked == {f"references/{path.name}" for path in REFERENCES}
    assert all((SKILL / link).exists() for link in linked)


@pytest.mark.parametrize("path", REFERENCES, ids=reference_ids)
def test_references_are_one_level_deep_portable_and_plain(path):
    text = path.read_text()
    assert "references/" not in text, "chains to another reference"
    assert not HOST_SPECIFIC.findall(text)
    assert not re.findall(r"\b(?:MUST|NEVER|ALWAYS|IMPORTANT|CRITICAL)\b", text)
    assert len(text.splitlines()) < 300, "needs a table of contents, or splitting"


def stated_limits() -> dict[str, int]:
    text = (SKILL / "references" / "structure.md").read_text()
    return {name: int(value) for name, value in re.findall(r"^\| ([A-Z][\w ]+) \| (\d+) \|", text, re.M)}


def test_module_limit_is_one_number_in_the_guidance_and_the_hook():
    hook_limit = int(re.search(r"^LARGE_FILE_LINES = (\d+)", HOOK.read_text(), re.M).group(1))
    assert stated_limits()["Lines in a module"] == hook_limit


def test_stated_limits_are_what_ruff_defaults_to():
    if not shutil.which("ruff"):
        pytest.skip("ruff isn't installed, so the stated defaults weren't compared")
    settings = subprocess.run(["ruff", "check", "--isolated", "--show-settings", "."], capture_output=True, text=True, cwd=ROOT).stdout
    actual = {key: int(value) for key, value in re.findall(r"^linter\.([\w.]+) = (\d+)\s*$", settings, re.M)}
    limits = stated_limits()
    assert limits["Cyclomatic complexity"] == actual["mccabe.max_complexity"]
    assert limits["Branches in a function"] == actual["pylint.max_branches"]
    assert limits["Statements in a function"] == actual["pylint.max_statements"]
    assert limits["Return statements"] == actual["pylint.max_returns"]
    assert limits["Arguments"] == actual["pylint.max_args"]
    assert limits["Nested blocks"] == actual["pylint.max_nested_blocks"]
    assert limits["Public methods in a class"] == actual["pylint.max_public_methods"]
    assert limits["Line length"] == actual["line_length"]


def test_the_module_limit_is_what_pylint_defaults_to():
    if not shutil.which("pylint"):
        pytest.skip("pylint isn't installed, so the stated default wasn't compared")
    settings = subprocess.run(["pylint", "--generate-rcfile"], capture_output=True, text=True, cwd=ROOT).stdout
    assert stated_limits()["Lines in a module"] == int(re.search(r"^max-module-lines=(\d+)", settings, re.M).group(1))


# ------------------------------------------------------------ what the testing reference says about suites

def run_pytest(folder: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=folder, capture_output=True, text=True, timeout=60)


TRAPS = '''
import pytest

def test_same_name():
    assert False, "replaced by the definition below, so it never runs"

def test_same_name():
    assert True

def test_tuple_assert_cannot_fail():
    assert (1 == 2, "message")

def test_lines_after_the_raise_never_run():
    with pytest.raises(ValueError):
        raise ValueError("expected")
        assert False, "never reached"

class TestWithInit:
    def __init__(self):
        pass
    def test_never_collected(self):
        assert False

def check_outside_the_naming_pattern():
    assert False
'''


def test_the_traps_in_the_testing_reference_pass_while_checking_nothing(tmp_path):
    (tmp_path / "test_traps.py").write_text(TRAPS)
    (tmp_path / "foo_tests.py").write_text("def test_not_collected():\n    assert False\n")
    done = run_pytest(tmp_path)
    assert done.returncode == 0, done.stdout
    assert "3 passed" in done.stdout


def test_warnings_as_errors_expose_the_uncollected_class(tmp_path):
    (tmp_path / "test_class.py").write_text("class TestWithInit:\n    def __init__(self):\n        pass\n    def test_never(self):\n        assert False\n\n"
                                            "def test_other():\n    assert True\n")
    assert run_pytest(tmp_path).returncode == 0
    assert run_pytest(tmp_path, "-W", "error").returncode != 0


def test_selecting_nothing_exits_5_and_a_fully_skipped_run_exits_0(tmp_path):
    (tmp_path / "test_one.py").write_text("import pytest\n@pytest.mark.skip(reason='x')\ndef test_a():\n    assert False\n")
    assert run_pytest(tmp_path, "-k", "nomatch").returncode == 5
    assert run_pytest(tmp_path).returncode == 0


def test_unittest_finding_nothing_exits_as_stated(tmp_path):
    done = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover"], cwd=tmp_path, capture_output=True, timeout=60)
    assert done.returncode == (5 if sys.version_info >= (3, 12) else 0)


def test_a_misspelled_mock_assertion_behaves_as_stated():
    if sys.version_info >= (3, 12):
        with pytest.raises(AttributeError):
            mock.Mock().called_once_with(1)
    else:
        mock.Mock().called_once_with(1)


def test_patching_reaches_code_only_where_the_name_is_looked_up(tmp_path, monkeypatch):
    (tmp_path / "patched_lib.py").write_text("from os.path import exists\ndef present(path):\n    return exists(path)\n")
    monkeypatch.syspath_prepend(tmp_path)
    import patched_lib
    with mock.patch("os.path.exists", return_value=True):
        assert patched_lib.present("/nonexistent") is False
    with mock.patch("patched_lib.exists", return_value=True):
        assert patched_lib.present("/nonexistent") is True


def test_plain_mocks_accept_anything_and_autospec_does_not():
    assert mock.Mock().no_such_method()
    with pytest.raises(AttributeError):
        mock.create_autospec(Path).no_such_method()


def test_the_limits_a_rewrite_can_hit_behave_as_stated():
    compile("(" * 200 + "1" + ")" * 200, "<test>", "eval")
    with pytest.raises(SyntaxError, match="too many nested parentheses"):
        compile("(" * 201 + "1" + ")" * 201, "<test>", "eval")

    def depth(node):
        return 1 + max((depth(child) for child in ast.iter_child_nodes(node)), default=0)

    # One level deeper per term. Some versions already fail while parsing it, and the rest fail in the walk.
    with pytest.raises(RecursionError):
        depth(ast.parse(" + ".join(["a"] * 3000), mode="eval"))


# ------------------------------------------------------------ what the APIs and security reference says

@pytest.mark.parametrize("module, gone_from", [("imp", (3, 12)), ("asyncore", (3, 12)), ("asynchat", (3, 12)), ("smtpd", (3, 12)),
                                               ("cgi", (3, 13)), ("cgitb", (3, 13)), ("pipes", (3, 13)), ("telnetlib", (3, 13)),
                                               ("crypt", (3, 13)), ("nntplib", (3, 13)), ("distutils", (3, 12))])
def test_removed_modules_are_gone_on_this_interpreter(module, gone_from):
    if sys.version_info < gone_from:
        pytest.skip(f"still present before {gone_from}")
    # With no site packages, because setuptools installs a distutils shim that answers find_spec.
    code = "import importlib.util, sys; raise SystemExit(importlib.util.find_spec(sys.argv[1]) is not None)"
    assert subprocess.run([sys.executable, "-I", "-S", "-c", code, module], timeout=60).returncode == 0


def test_removed_attributes_are_gone_on_this_interpreter():
    if sys.version_info >= (3, 10):
        assert not hasattr(collections, "Mapping")
    if sys.version_info >= (3, 11):
        assert not hasattr(asyncio, "coroutine")
    if sys.version_info >= (3, 12):
        assert not hasattr(unittest.TestCase, "assertEquals") and not hasattr(unittest.TestCase, "assertRegexpMatches")


def test_utcnow_is_deprecated_on_supported_versions():
    if sys.version_info < (3, 12):
        pytest.skip("deprecated from 3.12")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(DeprecationWarning):
            datetime.datetime.utcnow()


def test_get_event_loop_with_no_loop_raises_from_3_14():
    if sys.version_info < (3, 14):
        pytest.skip("raises from 3.14")
    code = "import asyncio\ntry:\n    asyncio.get_event_loop()\nexcept RuntimeError:\n    raise SystemExit(7)\n"
    assert subprocess.run([sys.executable, "-B", "-c", code], timeout=60).returncode == 7


def test_a_type_checking_only_name_fails_when_annotations_are_evaluated(tmp_path):
    code = ("from typing import TYPE_CHECKING, get_type_hints\nif TYPE_CHECKING:\n    from decimal import Decimal\n"
            "def f(x: 'Decimal'):\n    pass\ntry:\n    get_type_hints(f)\nexcept NameError:\n    raise SystemExit(7)\n")
    assert subprocess.run([sys.executable, "-B", "-c", code], timeout=60).returncode == 7


def test_the_path_traps_behave_as_stated():
    assert os.path.join("/srv/uploads", "/etc/passwd") == "/etc/passwd"
    root = Path("/srv/uploads")
    assert not Path(root, "../../etc/passwd").resolve().is_relative_to(root.resolve())
    assert Path(root, "a/b.txt").resolve().is_relative_to(root.resolve())


@pytest.mark.parametrize("module", ["random", "email", "logging", "types"])
def test_a_local_module_shadows_the_standard_library(tmp_path, module):
    (tmp_path / f"{module}.py").write_text("raise SystemExit(7)\n")
    (tmp_path / "main.py").write_text(f"import {module}\n")
    # -S because site packages can import some of these first and hide the problem, as Homebrew's do for types.
    assert subprocess.run([sys.executable, "-B", "-S", "main.py"], cwd=tmp_path, timeout=60).returncode == 7


# ------------------------------------------------------------ what the runtime reference says

def test_a_task_group_error_is_not_caught_by_its_own_type():
    if sys.version_info < (3, 11):
        pytest.skip("TaskGroup is from 3.11")

    async def fail():
        raise ValueError("x")

    async def main():
        async with asyncio.TaskGroup() as group:
            group.create_task(fail())

    with pytest.raises(BaseExceptionGroup):  # noqa: F821  (a builtin from 3.11, and this line runs only there)
        asyncio.run(main())


def test_cancelling_to_thread_leaves_the_thread_running():
    finished = threading.Event()

    def work():
        time.sleep(0.1)
        finished.set()

    async def main():
        task = asyncio.create_task(asyncio.to_thread(work))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert finished.wait(5)


def test_a_submitted_exception_stays_in_the_future_until_asked_for():
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(lambda: 1 / 0)
    assert isinstance(future.exception(), ZeroDivisionError)


def test_subprocess_run_does_not_raise_without_check():
    command = [sys.executable, "-c", "raise SystemExit(3)"]
    assert subprocess.run(command, timeout=60).returncode == 3
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(command, check=True, timeout=60)


def test_each_python_scenario_points_at_a_real_case():
    scenarios = yaml.safe_load((ROOT / "evals" / "scenarios.yaml").read_text())["scenarios"]
    cases = {s["id"]: s.get("case") for s in scenarios if s["status"] == "python"}
    assert set(cases) == {f"s{number}" for number in range(40, 48)}
    for case in cases.values():
        folder = ROOT / "evals" / "cases" / "python" / case
        assert (folder / "prompt.md").exists() and (folder / "solutions" / "reference").is_dir() and list((folder / "solutions").glob("trap-*"))


# ------------------------------------------------------------ occam's own Python

def test_the_development_version_is_the_plugin_version():
    manifest = json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text())
    assert f'version = "{manifest["version"]}"' in (ROOT / "pyproject.toml").read_text()


def test_our_own_modules_stay_within_the_limit_we_recommend():
    limit = stated_limits()["Lines in a module"]
    ours = [path for folder in ("plugin", "adapters", "tests") for path in (ROOT / folder).rglob("*.py")]
    ours += (ROOT / "evals").glob("*.py")
    assert len(ours) > 20, "the glob found too little to mean anything"
    over = {str(path.relative_to(ROOT)): count for path in ours if (count := len(path.read_text().splitlines())) > limit}
    assert not over, f"over {limit} lines, so split along a seam: {over}"


# ------------------------------------------------------------ the coverage record

def test_coverage_map_tracks_each_aspect_and_its_python_scenarios():
    text = (ROOT / "docs" / "coverage-map.md").read_text()
    assert "## Python coverage, aspect by aspect" in text
    for number in range(40, 47):
        assert f"s{number}" in text
    for aspect in ("Auditing", "Structure", "Naming", "Docs", "Comments", "File size", "Large codebases", "Testing", "Notebooks"):
        assert re.search(rf"^\| {aspect}\b", text, re.M), aspect
