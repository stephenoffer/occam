"""Each test here is a defect an independent review confirmed. They must stay fixed."""

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from test_tools import Repo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import scan  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    made = Repo(path, tmp_path / "state")
    made.git("init", "-q")
    made.write(".gitignore", "__pycache__/\n.pytest_cache/\n")
    made.write("app/__init__.py", "")
    made.write("app/core.py", "def total(a, b):\n    return a + b\n")
    made.write("tests/__init__.py", "")
    made.write("tests/test_core.py", "from app.core import total\n\n\ndef test_total():\n    assert total(1, 2) == 3\n")
    made.commit("init")
    return made


# ---------------------------------------------------------------- nothing in the repository runs


@pytest.mark.parametrize("shadow", ["multiprocessing.py", "concurrent.py", "pickle.py"])
def test_a_large_scan_cant_import_a_shadowing_module(repo, tmp_path, shadow):
    marker = tmp_path / "ran"
    repo.write(shadow, f"open({str(marker)!r}, 'w').close()\n")
    for index in range(160):
        repo.write(f"src/m{index}.py", f"def f{index}():\n    return {index}\n")
    repo.commit()
    assert repo.occam("scan", "--no-cache", "--workers", "2").returncode == 0
    assert not marker.exists()


@pytest.mark.parametrize("command", [("coord", "status"), ("map",), ("gate",), ("scan", "--changed"), ("goal", "status")])
def test_programs_named_in_git_config_dont_run(repo, tmp_path, command):
    marker = tmp_path / "ran"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    hooks = repo.path / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    shutil.copy(script, hooks / "post-index-change")
    repo.git("config", "core.fsmonitor", str(script))
    repo.git("config", "filter.evil.clean", str(script))
    repo.git("config", "gpg.program", str(script))
    repo.git("config", "log.showSignature", "true")
    repo.write(".gitattributes", "*.py filter=evil\n")
    repo.write("app/core.py", "def total(a, b):\n    return a - b\n")
    repo.occam(*command)
    assert not marker.exists()


def test_a_repository_cant_plant_state(repo, tmp_path):
    planted = repo.path / ".git" / "occam"
    planted.mkdir()
    (planted / "occam.db").write_text("not what you think")
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (planted / "last-scan.json").symlink_to(outside)
    repo.env.pop("OCCAM_STATE_DIR")
    repo.env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n")
    done = repo.occam("scan")
    assert "mutable-default" in done.stdout
    assert outside.read_text() == "keep"
    assert str(tmp_path / "cache") in done.stdout


# ---------------------------------------------------------------- fix must not break code


# ---------------------------------------------------------------- fix must not touch anyone's work


def test_a_claim_needs_an_owner(repo):
    assert repo.occam("coord", "claim", "app/core.py").returncode == 2


# ---------------------------------------------------------------- no false all-clears


@pytest.mark.parametrize("name", ["with space.py", "naïve.py", "tab\tname.py", 'quo"te.py'])
def test_gate_sees_unusual_file_names(repo, name):
    repo.write(name, "x = 1\n")
    repo.commit()
    repo.write(name, "x = 1\n\n\ndef charge(card):\n    pass\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "stub-body" in done.stdout, done.stdout


def test_gate_honors_nothing_from_diff_config(repo):
    repo.git("config", "diff.mnemonicPrefix", "true")
    repo.git("config", "diff.noprefix", "true")
    repo.write("app/core.py", "def charge(card):\n    pass\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "stub-body" in done.stdout


def test_binary_diff_attribute_doesnt_hide_a_change(repo):
    repo.write(".gitattributes", "*.py -diff\n")
    repo.commit()
    repo.write("app/core.py", "def charge(card):\n    pass\n")
    assert repo.occam("gate").returncode == 1


@pytest.mark.parametrize("command", [("gate", "--base", "nosuch"), ("scan", "--diff", "nosuch"), ("gate", "typo.py"), ("scan", "typo.py")])
def test_a_bad_target_is_an_error_and_not_a_pass(repo, command):
    assert repo.occam(*command).returncode == 2


def test_a_deleted_test_file_blocks(repo):
    (repo.path / "tests/test_core.py").unlink()
    done = repo.occam("gate")
    assert done.returncode == 1 and "test-weakened" in done.stdout


def test_a_renamed_test_with_assertions_dropped_blocks(repo):
    repo.git("mv", "tests/test_core.py", "tests/test_math.py")
    repo.write("tests/test_math.py", "from app.core import total\n\n\ndef test_total():\n    total(1, 2)\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and ("test-weakened" in done.stdout or "test-no-assert" in done.stdout)


def test_staged_work_in_a_repository_with_no_commits_is_seen(tmp_path):
    made = Repo(tmp_path / "r", tmp_path / "state")
    (tmp_path / "r").mkdir()
    made.git("init", "-q")
    made.write("a.py", "def charge(card):\n    pass\n")
    made.git("add", "a.py")
    done = made.occam("gate")
    assert done.returncode == 1 and "stub-body" in done.stdout


def test_a_syntax_error_in_a_changed_file_blocks(repo):
    repo.write("app/core.py", "def total(a, b:\n    return a + b\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "unparseable" in done.stdout


def test_gate_says_what_it_couldnt_read(repo):
    repo.write("big.py", "x = 1\n" * 300_000)
    done = repo.occam("gate")
    assert "NOT CHECKED" in done.stdout and "big.py" in done.stdout
    assert repo.occam("gate", "--strict").returncode == 1


def test_a_generated_by_chatgpt_header_doesnt_hide_a_file(repo):
    repo.write("app/x.py", "# Generated by ChatGPT\nAPI_KEY = 'abc123def456ghi789'\ndef f(x):\n    return eval(x)\n")
    done = repo.occam("scan")
    assert "hardcoded-secret" in done.stdout and "dynamic-eval" in done.stdout


@pytest.mark.parametrize("header", ["// Code generated by protoc-gen-go. DO NOT EDIT.", "# @generated by bazel", "# auto-generated by openapi-generator"])
def test_real_generated_files_are_skipped_and_named(repo, header):
    repo.write("app/gen.py", f"{header}\ndef f(x=[]):\n    return x\n")
    done = repo.occam("scan")
    assert "mutable-default" not in done.stdout and "generated" in done.stdout


def test_a_function_deleted_but_still_called_blocks(repo):
    repo.write("app/core.py", "def other():\n    return 1\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "phantom-local-import" in done.stdout


def test_a_function_deleted_but_called_through_the_module_blocks(repo):
    repo.write("app/core.py", "def total(a, b):\n    return a + b\n\n\ndef extra():\n    return 1\n")
    repo.write("app/user.py", "from app import core\n\nprint(core.extra())\n")
    repo.commit()
    repo.write("app/core.py", "def total(a, b):\n    return a + b\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "phantom-local-import" in done.stdout


def test_silencing_is_reported_by_gate(repo):
    repo.write(".occam.json", '{"disable": ["stub-body"]}')
    repo.write("app/x.py", "def charge(card):\n    pass\n\n\ndef f(x=[]):  # occam: ignore[mutable-default] on purpose\n    return x\n")
    done = repo.occam("gate")
    assert "Silenced here" in done.stdout and ".occam.json" in done.stdout


@pytest.mark.parametrize("move", ["delete", "rename"])
def test_goal_sees_a_forbidden_path_deleted_or_renamed(repo, move):
    repo.write("migrations/1.sql", "SELECT 1;\n")
    repo.commit()
    repo.occam("goal", "init", "x")
    repo.occam("goal", "add", "works", "--check", f"{sys.executable} -c pass")
    repo.occam("goal", "constrain", "--forbid", "migrations/*")
    if move == "delete":
        (repo.path / "migrations/1.sql").unlink()
    else:
        repo.git("mv", "migrations/1.sql", "other.sql")
    done = repo.occam("goal", "verify")
    assert done.returncode == 1 and "VIOLATED" in done.stdout


def test_goal_with_a_bad_base_isnt_verified(repo):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "add", "works", "--check", f"{sys.executable} -c pass")
    assert repo.occam("goal", "verify", "--base", "nosuch").returncode == 2


def test_goal_evidence_goes_stale_inside_an_untracked_folder(repo):
    repo.write("nw/a.py", "x = 1\n")
    repo.occam("goal", "init", "x")
    repo.occam("goal", "add", "works", "--check", f"{sys.executable} -c pass")
    repo.occam("goal", "verify")
    repo.write("nw/a.py", "x = 2\n")
    assert "stale" in repo.occam("goal", "status").stdout


# ---------------------------------------------------------------- concurrency


def in_parallel(count, action):
    results = [None] * count

    def run(index):
        results[index] = action(index)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_only_one_agent_wins_a_claim_on_a_fresh_database(repo, tmp_path):
    for attempt in range(3):
        repo.env["OCCAM_STATE_DIR"] = str(tmp_path / f"fresh{attempt}")
        results = in_parallel(12, lambda index: repo.occam("coord", "claim", "app/core.py", "--owner", f"a{index}").returncode)
        assert results.count(0) == 1, results


def test_parallel_goal_additions_all_survive(repo):
    repo.occam("goal", "init", "x")
    in_parallel(12, lambda index: repo.occam("goal", "add", f"req {index}"))
    status = repo.occam("goal", "status").stdout
    assert sum(f"req {index}" in status for index in range(12)) == 12


# ---------------------------------------------------------------- the ledger tells the truth


def _note(repo, identifier):
    from occam_tools import workflow
    previous = os.environ.get("OCCAM_STATE_DIR")
    os.environ["OCCAM_STATE_DIR"] = repo.env["OCCAM_STATE_DIR"]
    try:
        with workflow.database(repo.path) as db:
            return db.execute("SELECT data FROM ledger WHERE id = ?", (identifier,)).fetchone()[0]
    finally:
        if previous is None:
            os.environ.pop("OCCAM_STATE_DIR")
        else:
            os.environ["OCCAM_STATE_DIR"] = previous


# ---------------------------------------------------------------- odd input doesn't stop a scan


@pytest.mark.parametrize("content", ["[]", '{"cells": [1]}', '{"cells": [{"cell_type": "code", "source": 5}]}', '{"cells": 3}', "not json"])
def test_strange_notebooks_dont_stop_a_scan(repo, content):
    repo.write("a.ipynb", content)
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n")
    done = repo.occam("scan")
    assert done.returncode == 0 and "mutable-default" in done.stdout


@pytest.mark.parametrize("config", ['{"ignore": 5}', '{"disable": "x"}', "[]", "nope", '{"ignore": [1, null]}'])
def test_strange_config_doesnt_stop_a_scan(repo, config):
    repo.write(".occam.json", config)
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n")
    assert "mutable-default" in repo.occam("scan").stdout


def test_a_fifo_doesnt_hang_a_scan(tmp_path):
    made = Repo(tmp_path, tmp_path / ".state")
    made.write("a.py", "def f(x=[]):\n    return x\n")
    os.mkfifo(tmp_path / "pipe.py")
    os.mkfifo(tmp_path / "noext")
    assert "mutable-default" in made.occam("scan").stdout


def test_a_byte_order_mark_doesnt_stop_parsing(repo):
    (repo.path / "app/x.py").write_bytes(b"\xef\xbb\xbfdef f(x=[]):\n    return x\n")
    done = repo.occam("scan")
    assert "mutable-default" in done.stdout and "unparseable" not in done.stdout


@pytest.mark.parametrize("text", ["/*" * 150_000, "<!--" * 100_000, '"""' * 3 + "'''" * 3 + "\n"])
def test_repeated_openers_stay_fast(text):
    started = time.monotonic()
    scan.scan_text("a.ts", text)
    scan.scan_text("a.html", text)
    scan.scan_text("a.py", "x = 1\n" + text)
    assert time.monotonic() - started < 15


# ---------------------------------------------------------------- honest numbers at the extremes


def test_map_on_languages_without_rules_still_counts_them(tmp_path):
    made = Repo(tmp_path, tmp_path / ".state")
    made.write("lib/a.dart", "void main() {\n  print(1);\n}\n" * 2000)
    made.write("lib/b.ex", "def f do\n  1\nend\n" * 2000)
    data = json.loads(made.occam("map", "--format", "json").stdout)
    assert data["lines"] > 10000 and data["tier"] != "cell"


def test_empty_repository_reports_nothing_to_divide(tmp_path):
    made = Repo(tmp_path, tmp_path / ".state")
    for mode in ("read", "write"):
        plan = json.loads(made.occam("partition", "--format", "json", "--mode", mode).stdout)
        assert plan["agents"] == 0
    assert "no recognized source" in made.occam("map").stdout


def test_a_zero_agent_limit_is_honored_honestly(repo):
    for index in range(4):
        repo.write(f"pkg{index}/mod.py", "x = 1\n" * 8000)
    plan = json.loads(repo.occam("partition", "--format", "json", "--max-agents", "0").stdout)
    assert plan["agents"] == 0 and "limit is zero" in plan["reason"]


@pytest.mark.parametrize("lines", [5000, 13000, 30000, 200000])
def test_map_and_partition_agree(repo, lines):
    for index in range(4):
        repo.write(f"pkg{index}/mod.py", "x = 1\n" * (lines // 4))
    # No time cap: a capped map deliberately leaves out "agents", so a loaded machine would otherwise decide this test.
    mapped = json.loads(repo.occam("map", "--format", "json", "--max-seconds", "0").stdout)["agents"]["readers_for_audit"]
    assert mapped == json.loads(repo.occam("partition", "--format", "json", "--max-seconds", "0").stdout)["agents"]


@pytest.mark.parametrize("files", [
    {"go.mod": "module m\n", "a/a.go": 'package a\nimport "m/b"\nvar X = b.Y\n', "b/b.go": "package b\nvar Y = 1\n"},
    {"a/A.java": "import b.B;\nclass A { B b; }\n", "b/B.java": "package b;\nclass B {}\n"},
    {"tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}', "src/a.ts": "import { y } from '@/b';\nuse(y);\n", "src/b.ts": "export const y = 1;\n"},
])
def test_writers_arent_told_coupled_code_is_independent(tmp_path, files):
    made = Repo(tmp_path, tmp_path / ".state")
    for name, content in files.items():
        made.write(name, content)
    plan = json.loads(made.occam("partition", "--format", "json", "--mode", "write", "--budget", "1").stdout)
    assert plan["agents"] == 1


# ---------------------------------------------------------------- tools tell the truth


def test_mutate_doesnt_blame_tests_for_an_installed_copy(tmp_path):
    installed = tmp_path / "site"
    (installed / "lib").mkdir(parents=True)
    (installed / "lib" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    made = Repo(tmp_path / "r", tmp_path / "state")
    (tmp_path / "r").mkdir()
    made.git("init", "-q")
    made.write("lib/__init__.py", "")
    made.write("lib/calc.py", "def add(a, b):\n    return a + b\n")
    made.write("tests/test_calc.py", "import importlib.util\nspec = importlib.util.spec_from_file_location('calc', " + repr(str(installed / "lib" / "calc.py")) + ")\ncalc = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(calc)\n\n\ndef test_add():\n    assert calc.add(1, 2) == 3\n")
    made.commit()
    done = made.occam("mutate", "--cmd", f"{sys.executable} -m pytest -q -p no:cacheprovider tests", "lib")
    assert "Not measured" in done.stdout and "nothing protects" not in done.stdout


def test_a_committed_baseline_works_on_a_fresh_machine(repo, tmp_path):
    repo.write("app/old.py", "def f(x=[]):\n    return x\n")
    baseline = repo.path / ".occam-baseline.json"
    repo.occam("baseline", "write", "--out", str(baseline))
    repo.env["OCCAM_STATE_DIR"] = str(tmp_path / "fresh-machine")
    assert repo.occam("scan", "--baseline", str(baseline), "--fail-on", "high").returncode == 0
    repo.write("app/new.py", "def g(y=[]):\n    return y\n")
    assert repo.occam("scan", "--baseline", str(baseline), "--fail-on", "high").returncode == 1


def test_new_only_warns_when_there_is_no_baseline(repo):
    done = repo.occam("scan", "--new-only")
    assert "No baseline" in done.stderr


def test_tools_leave_no_cache_in_the_tree(repo):
    if not shutil.which("ruff"):
        pytest.skip("ruff isn't installed")
    repo.occam("tools", "--run", "--only", "ruff")
    assert not (repo.path / ".ruff_cache").exists()


def test_golden_reports_a_missing_command_cleanly(repo):
    done = repo.occam("golden", "record", "x", "--", "no-such-program-here")
    assert done.returncode == 2 and "Traceback" not in done.stderr


# ---------------------------------------------------------------- second review


@pytest.mark.parametrize("name", ["filter.a=b.clean", "filter.a=b.smudge"])
def test_a_filter_with_an_equals_sign_in_its_name_is_blanked(repo, tmp_path, name):
    marker = tmp_path / "ran"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    repo.git("config", name, str(script))
    repo.write(".gitattributes", "*.py filter=a=b\n")
    repo.write("app/core.py", "def total(a, b):\n    return a - b\n")
    repo.occam("coord", "status")
    repo.occam("gate")
    assert not marker.exists()


def test_a_submodules_filter_doesnt_run(repo, tmp_path):
    marker = tmp_path / "ran"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    inner = repo.path / "sub"
    inner.mkdir()
    made = Repo(inner, tmp_path / "other")
    made.git("init", "-q")
    made.write(".gitattributes", "*.py filter=evil\n")
    made.write("m.py", "x = 1\n")
    made.commit()
    made.git("config", "filter.evil.clean", str(script))  # after the commit, so only occam's own calls could run it
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{made.git('rev-parse', 'HEAD').strip()},sub")
    made.write("m.py", "x = 2\n")
    repo.occam("coord", "status")
    repo.occam("gate")
    assert not marker.exists()


def test_gate_sees_a_notebook_edit(repo):
    notebook = {"cells": [{"cell_type": "code", "execution_count": 1, "source": ["x = 1\n"], "outputs": []}]}
    repo.write("a.ipynb", json.dumps(notebook))
    repo.commit()
    notebook["cells"][0]["source"] = ["x = 1\n", "def f(y=[]):\n", "    return y\n"]
    repo.write("a.ipynb", json.dumps(notebook))
    done = repo.occam("gate")
    assert done.returncode == 1 and "mutable-default" in done.stdout


def test_an_added_line_that_looks_like_a_diff_header_hides_nothing(repo):
    repo.write("app/core.py", '"""\ndoc\n"""\nx = 1\n\n\n' + "y = 2\n" * 10)
    repo.commit()
    repo.write("app/core.py", '"""\ndoc\n++ b/nothing\n"""\nx = 1\n\n\n' + "y = 2\n" * 10 + "\n\ndef charge(card):\n    pass\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "stub-body" in done.stdout


@pytest.mark.parametrize("name", ['café"x.py', 'a\\b.py'])
def test_gate_handles_quoted_non_ascii_names(repo, name):
    repo.write(name, "x = 1\n")
    repo.commit()
    repo.write(name, "x = 1\n\n\ndef charge(card):\n    pass\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "stub-body" in done.stdout


def test_gate_names_changed_files_in_skipped_folders(repo):
    repo.write("src/target/a.py", "x = 1\n")
    repo.commit()
    repo.write("src/target/a.py", "def charge(card):\n    pass\n")
    assert "NOT CHECKED" in repo.occam("gate").stdout


def test_naming_a_file_in_a_skipped_folder_reads_it(repo):
    repo.write("src/build/b.py", "def charge(card):\n    pass\n")
    done = repo.occam("gate", "src/build/b.py")
    assert done.returncode == 1 and "stub-body" in done.stdout


def test_a_path_outside_the_project_is_an_error(repo, tmp_path):
    outside = tmp_path / "elsewhere.py"
    outside.write_text("x = 1\n")
    assert repo.occam("gate", "app/core.py", str(outside)).returncode == 2
    assert repo.occam("scan", "app/core.py", str(outside)).returncode == 2


def test_gate_reads_the_staged_version(repo):
    repo.write("app/core.py", "def charge(card):\n    pass\n")
    repo.git("add", "app/core.py")
    repo.write("app/core.py", "def total(a, b):\n    return a + b\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "stub-body" in done.stdout


def test_a_deleted_module_still_imported_blocks(repo):
    repo.write("helpers.py", "def h():\n    return 1\n")
    repo.write("app/user.py", "import helpers\n\nprint(helpers.h())\n")
    repo.commit()
    (repo.path / "helpers.py").unlink()
    done = repo.occam("gate")
    assert done.returncode == 1 and "phantom" in done.stdout


def test_a_string_saying_do_not_edit_doesnt_hide_a_file(repo):
    repo.write("app/x.py", 'LABEL = "Do not edit this field"\n\n\ndef f(y=[]):\n    return y\n')
    assert "mutable-default" in repo.occam("scan").stdout


def test_goal_keeps_what_was_added_while_checks_ran(repo, tmp_path):
    repo.occam("goal", "init", "x")
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(2)\n")
    repo.occam("goal", "add", "slow check", "--check", f"{sys.executable} {slow}")
    results = []
    verify = threading.Thread(target=lambda: results.append(repo.occam("goal", "verify")))
    verify.start()
    time.sleep(0.8)
    repo.occam("goal", "add", "added meanwhile")
    repo.occam("goal", "constrain", "--forbid", "migrations/*")
    verify.join()
    status = repo.occam("goal", "status").stdout
    assert "added meanwhile" in status and "migrations" in status


def test_goal_scope_works_outside_git(tmp_path):
    made = Repo(tmp_path, tmp_path / ".state")
    made.write("a.py", "x = 1\n")
    made.write("migrations/1.sql", "SELECT 1;\n")
    made.occam("goal", "init", "x")
    made.occam("goal", "add", "works", "--check", f"{sys.executable} -c pass")
    made.occam("goal", "constrain", "--forbid", "migrations/*")
    assert made.occam("goal", "verify").returncode == 0
    made.write("migrations/1.sql", "DROP TABLE t;\n")
    done = made.occam("goal", "verify")
    assert done.returncode == 1 and "VIOLATED" in done.stdout


def test_a_claim_on_a_parent_conflicts_with_a_held_child(repo):
    assert repo.occam("coord", "claim", "app/core.py", "--owner", "a").returncode == 0
    assert repo.occam("coord", "claim", ".", "--owner", "b").returncode == 1
    assert repo.occam("coord", "claim", "app", "--owner", "b").returncode == 1
    assert repo.occam("coord", "check", "app", "--owner", "b").returncode == 1


def test_check_on_a_folder_sees_a_dirty_child(repo):
    repo.write("app/core.py", "x = 1\n")
    assert repo.occam("coord", "check", "app").returncode == 1


@pytest.mark.parametrize("line", ['API_KEY = "abc123def456ghi789"', 'DB = "postgres://admin:s3cr3tpw@db.internal/prod"', 'KEY = os.getenv("PAY_API_KEY", "pb_live_9f8e7d6c5b4a")'])
def test_secret_values_never_reach_saved_or_json_output(repo, tmp_path, line):
    repo.write("app/x.py", f"import os\n{line}\n")
    value = line.split('"')[-2] if "getenv" in line else line.split('"')[1]
    done = repo.occam("scan", "--format", "json", "--min-confidence", "low")
    assert value not in done.stdout
    saved = repo.occam("scan").stdout.split("Full results: ")[1].strip()
    assert value not in Path(saved).read_text()


def test_prefixes_of_flags_are_refused(repo):
    repo.write("app/x.py", "import os\nprint(1)\n")
    repo.commit()
    assert repo.occam("scan", "--no-cach").returncode == 2


@pytest.mark.parametrize("extra", [
    {"package.json": '{"workspaces": ["a", "b"]}'},
    {"tsconfig.json": '{"compilerOptions": {"baseUrl": "."}}'},
    {"webpack.config.js": "module.exports = {};\n"},
])
def test_js_with_hidden_import_routes_isnt_called_independent(tmp_path, extra):
    made = Repo(tmp_path, tmp_path / ".state")
    made.write("a/a.ts", "import { y } from 'b/b';\nuse(y);\n")
    made.write("b/b.ts", "export const y = 1;\n")
    for name, content in extra.items():
        made.write(name, content)
    plan = json.loads(made.occam("partition", "--format", "json", "--mode", "write", "--budget", "1").stdout)
    assert plan["agents"] == 1


# ---------------------------------------------------------------- third review


@pytest.mark.parametrize("before, after, rule", [
    ("def charge(card):\n    return card.pay()\n", "def charge(card):\n    pass\n", "stub-body"),
    ("try:\n    f()\nexcept Exception:\n    raise\n", "try:\n    f()\nexcept Exception:\n    pass\n", "swallowed-exception"),
    ("import subprocess\n\n\ndef run(c):\n    subprocess.run(\n        c,\n        check=True,\n    )\n", "import subprocess\n\n\ndef run(c):\n    subprocess.run(\n        c,\n        shell=True,\n    )\n", "shell-injection"),
])
def test_gate_sees_a_finding_reported_on_an_unchanged_line(repo, before, after, rule):
    repo.write("app/x.py", before)
    repo.commit()
    repo.write("app/x.py", after)
    done = repo.occam("gate")
    assert done.returncode == 1 and rule in done.stdout, done.stdout


def test_gate_still_ignores_what_was_already_there(repo):
    repo.write("app/x.py", "def f(x=[]):\n    return x\n")
    repo.commit()
    repo.write("app/x.py", "def f(x=[]):\n    return x\n\n\nprint(f())\n")
    assert "mutable-default" not in repo.occam("gate").stdout
    assert "mutable-default" not in repo.occam("scan", "--changed").stdout


def test_scan_changed_sees_a_notebook_edit(repo):
    notebook = {"cells": [{"cell_type": "code", "execution_count": 1, "source": ["x = 1\n"], "outputs": []}]}
    repo.write("a.ipynb", json.dumps(notebook))
    repo.commit()
    notebook["cells"][0]["source"] = ["x = 1\n", "def f(y=[]):\n", "    return y\n"]
    repo.write("a.ipynb", json.dumps(notebook))
    assert "mutable-default" in repo.occam("scan", "--changed").stdout


def test_a_pure_staged_rename_breaking_an_importer_blocks(repo):
    repo.write("lib.py", "def h():\n    return 1\n")
    repo.write("main.py", "import lib\n\nprint(lib.h())\n")
    repo.commit()
    repo.git("mv", "lib.py", "lib2.py")
    done = repo.occam("gate")
    assert "No changes" not in done.stdout
    assert done.returncode == 1 and "phantom" in done.stdout


def test_submodules_are_named_as_unchecked(repo, tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    made = Repo(inner, tmp_path / "other")
    made.git("init", "-q")
    made.write("m.py", "x = 1\n")
    made.commit()
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{made.git('rev-parse', 'HEAD').strip()},subm")
    done = repo.occam("gate")
    assert "No changes" not in done.stdout and "submodules" in done.stdout and "subm" in done.stdout
    assert "Submodules" in repo.occam("coord", "status").stdout
