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


@pytest.mark.parametrize("command", [("coord", "status"), ("map",), ("gate",), ("scan", "--changed"), ("fix",), ("goal", "status")])
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


def run_fix(repo, *args):
    """Import removal is opt-in, and these tests are about what it must still refuse when asked."""
    repo.commit()
    return repo.occam("fix", "--apply", "--rule", "unused-import", "--rule", "ai-residue", *args)


def test_two_statements_on_a_line_are_left_alone(repo):
    source = "import os, re; import sys\nprint(re, sys)\n"
    repo.write("app/x.py", source)
    assert run_fix(repo).returncode == 0
    assert (repo.path / "app/x.py").read_text() == source


@pytest.mark.parametrize("source", ["import models\nprint(1)\n", "from app import routes\nprint(1)\n", "import requests\nprint(1)\n"])
def test_imports_that_may_have_side_effects_stay(repo, source):
    repo.write("app/x.py", source)
    done = run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source
    assert "Check by hand" in done.stdout


def test_fixture_imports_in_conftest_stay(repo):
    source = "from os import sep\nprint(1)\n"
    repo.write("conftest.py", source)
    run_fix(repo)
    assert (repo.path / "conftest.py").read_text() == source


def test_a_name_another_file_reaches_through_this_module_stays(repo):
    source = "import json\nprint(1)\n"
    repo.write("helper.py", source)
    repo.write("user.py", "import helper\nprint(helper.json.dumps({}))\n")
    run_fix(repo)
    assert (repo.path / "helper.py").read_text() == source


def test_a_mock_patch_target_stays(repo):
    source = "import time\nprint(1)\n"
    repo.write("svc.py", source)
    repo.write("tests/test_svc.py", "from unittest import mock\n\n\ndef test_x():\n    with mock.patch('svc.time'):\n        assert True\n")
    run_fix(repo)
    assert (repo.path / "svc.py").read_text() == source


def test_a_reexport_from_a_private_module_stays(repo):
    source = "from _ssl import HAS_SNI\nprint(1)\n"
    repo.write("app/x.py", source)
    done = run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source and "re-export" in done.stdout


def test_a_librarys_public_from_imports_stay(repo):
    source = "from os import sep\nprint(1)\n"
    repo.write("pyproject.toml", '[project]\nname = "lib"\n')
    repo.write("lib/x.py", source)
    done = run_fix(repo)
    assert (repo.path / "lib/x.py").read_text() == source and "re-export" in done.stdout


def test_a_safe_stdlib_import_is_still_removed(repo):
    repo.write("app/x.py", "import os\nimport json\nprint(json)\n")
    assert run_fix(repo).returncode == 0
    assert (repo.path / "app/x.py").read_text() == "import json\nprint(json)\n"


def test_removing_an_import_cant_create_a_docstring(repo):
    source = "import os\n'not a docstring'\nprint(1)\n"
    repo.write("app/x.py", source)
    done = run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source
    assert "docstring" in done.stdout


@pytest.mark.parametrize("name, source", [
    ("A.java", 'class A {\n  String s = """\n    // Here is the updated code\n    """;\n}\n'),
    ("a.rs", 'fn f() {\n    let s = r#"\n    // Here is the updated code\n    "#;\n}\n'),
    ("a.sh", "#!/bin/sh\nset -e\ncat <<EOF\n# Here is the updated code\nEOF\n"),
    ("a.rb", "s = <<~EOT\n  # Here is the updated code\nEOT\n"),
    ("a.ts", "const r = a / b;\nconst t = `\n// Here is the updated code\n`;\n"),
])
def test_other_languages_are_never_edited(repo, name, source):
    repo.write(name, source)
    run_fix(repo)
    assert (repo.path / name).read_text() == source


@pytest.mark.parametrize("comment", [
    "# Changed from 30s to 5s because the vendor times out",
    "# Modified: 2019 under the original license",
    "# Note to reviewer: do not reorder these",
    "# Here's the updated logic, kept because the vendor requires it",
])
def test_comments_carrying_a_reason_stay(repo, comment):
    source = f"{comment}\nx = 1\n"
    repo.write("app/x.py", source)
    run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source


def test_a_string_that_looks_like_a_comment_stays(repo):
    source = 's = """\n# Here\'s the updated function\n"""\nprint(s)\n'
    repo.write("app/x.py", source)
    run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source


# ---------------------------------------------------------------- fix must not touch anyone's work


def test_a_file_in_an_untracked_folder_counts_as_uncommitted(repo):
    repo.write("nw/m.py", "import os\nprint(1)\n")
    done = repo.occam("fix", "--apply", "--rule", "unused-import")
    assert "uncommitted" in done.stdout
    assert "import os" in (repo.path / "nw/m.py").read_text()


def test_hiding_untracked_files_in_config_doesnt_help(repo):
    repo.git("config", "status.showUntrackedFiles", "no")
    repo.write("nw/m.py", "import os\nprint(1)\n")
    repo.occam("fix", "--apply", "--rule", "unused-import")
    assert "import os" in (repo.path / "nw/m.py").read_text()


def test_outside_git_nothing_is_edited_without_saying_so(tmp_path):
    made = Repo(tmp_path, tmp_path / ".state")
    made.write("a.py", "import os\nprint(1)\n")
    done = made.occam("fix", "--apply", "--rule", "unused-import")
    assert "isn't a git repository" in done.stdout
    assert "import os" in (tmp_path / "a.py").read_text()


def test_a_claimed_folder_protects_its_files(repo):
    repo.write("src/a.py", "import os\nprint(1)\n")
    repo.commit()
    assert repo.occam("coord", "claim", "src", "--owner", "other").returncode == 0
    assert repo.occam("coord", "check", "src/a.py", "--owner", "me").returncode == 1
    assert "claimed by other" in repo.occam("fix", "--apply", "--rule", "unused-import").stdout
    assert "import os" in (repo.path / "src/a.py").read_text()
    repo.occam("ledger", "sync", "--min-confidence", "low")
    assert "src/a.py" not in repo.occam("ledger", "next", "--owner", "me", "--size", "50").stdout


def test_a_claim_needs_an_owner(repo):
    assert repo.occam("coord", "claim", "app/core.py").returncode == 2


def test_fix_reads_lines_from_the_bytes_it_edits(repo, monkeypatch):
    from occam_tools import fix
    repo.write("app/x.py", "# Here's the updated function\nx = 1\n")
    repo.commit()
    # Findings are recomputed inside, so a stale scan's line numbers can't reach this.
    text = "# KEEP this one\n# Here's the updated function\nx = 1\n"

    class Empty:
        files: list = []
        root = repo.path

    after, _, _ = fix._plan(Empty, "app/x.py", text, {"ai-residue"})
    assert after == "# KEEP this one\nx = 1\n"


def test_a_file_that_isnt_utf8_survives(repo):
    (repo.path / "app").mkdir(exist_ok=True)
    (repo.path / "app/x.py").write_bytes(b"# caf\xe9\nimport os\nprint(1)\n")
    done = run_fix(repo)
    assert done.returncode == 0, done.stderr
    assert b"caf\xe9" in (repo.path / "app/x.py").read_bytes()
    assert not list((repo.path / "app").glob(".x.py.*")), "no temp file left behind"


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


def test_ledger_next_gives_each_file_to_one_agent_under_load(repo):
    for index in range(10):
        repo.write(f"app/m{index}.py", "def f(x=[]):\n    return x\n")
    repo.commit()
    repo.occam("ledger", "sync")
    outputs = in_parallel(10, lambda index: repo.occam("ledger", "next", "--owner", f"a{index}", "--size", "5", "--tier", "B").stdout)
    files = [line.split(" in ")[-1].rstrip(":") for output in outputs for line in output.split("\n")[:1] if output.startswith("Batch")]
    assert len(files) == len(set(files))


def test_abandoned_work_is_released(repo, monkeypatch):
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n")
    repo.commit()
    repo.occam("ledger", "sync")
    assert "Batch" in repo.occam("ledger", "next", "--owner", "dead", "--tier", "B").stdout
    assert "Nothing left" in repo.occam("ledger", "next", "--owner", "alive", "--tier", "B").stdout
    from occam_tools import workflow
    monkeypatch.setenv("OCCAM_STATE_DIR", repo.env["OCCAM_STATE_DIR"])
    with workflow.database(repo.path) as db:
        db.execute("UPDATE ledger SET updated = 0")
    assert "Batch" in repo.occam("ledger", "next", "--owner", "alive", "--tier", "B").stdout


# ---------------------------------------------------------------- the ledger tells the truth


def tracked(repo, code="def f(x=[]):\n    return x\n"):
    repo.write("app/bad.py", code)
    repo.commit()
    repo.occam("ledger", "sync")
    return json.loads(repo.occam("scan", "--format", "json", "--rule", "mutable-default").stdout)["findings"][0]["id"]


def test_sync_keeps_a_triage_note(repo):
    identifier = tracked(repo)
    repo.occam("ledger", "set", "--ids", identifier, "--status", "false-positive", "--note", "shared on purpose")
    repo.occam("ledger", "sync")
    assert "shared on purpose" in repo.occam("ledger", "report").stdout + _note(repo, identifier)


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


def test_a_stricter_sync_doesnt_mark_lower_findings_fixed(repo):
    repo.write("app/bad.py", "def getUser():\n    return 1\n\n\ndef load_a():\n    return 1\n\n\ndef load_b():\n    return 1\n\n\ndef load_c():\n    return 1\n")
    repo.commit()
    repo.occam("ledger", "sync", "--min-confidence", "medium")
    assert "0 no longer present" in repo.occam("ledger", "sync", "--min-confidence", "high").stdout


@pytest.mark.parametrize("breakage", ["def f(x=[]:\n    return x\n", "# Code generated by protoc. DO NOT EDIT.\ndef f(x=[]):\n    return x\n"])
def test_a_file_that_wasnt_read_proves_nothing_is_fixed(repo, breakage):
    tracked(repo)
    repo.write("app/bad.py", breakage)
    assert "0 no longer present" in repo.occam("ledger", "sync").stdout


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
    mapped = json.loads(repo.occam("map", "--format", "json").stdout)["agents"]["readers_for_audit"]
    assert mapped == json.loads(repo.occam("partition", "--format", "json").stdout)["agents"]


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


def test_a_required_filter_cant_turn_a_failure_into_no_changes(repo, tmp_path):
    repo.git("config", "filter.x.clean", "cat")
    repo.git("config", "filter.x.required", "true")
    repo.write(".gitattributes", "*.py filter=x\n")
    repo.commit()
    repo.write("app/core.py", "def total(a, b):\n    breakpoint()\n    return a + b\n")
    done = repo.occam("gate")
    assert done.returncode != 0 and "No changes" not in done.stdout
    fixed = repo.occam("fix", "--apply", "--rule", "unused-import")
    assert "fixed app/core.py" not in fixed.stdout


def test_a_git_failure_is_reported_and_edits_nothing(repo):
    repo.write("app/x.py", "import os\nprint(1)\n")
    (repo.path / ".git" / "index").write_bytes(b"corrupt")
    assert "failed" in repo.occam("gate").stdout
    done = repo.occam("fix", "--apply", "--rule", "unused-import")
    assert done.returncode == 2 and "import os" in (repo.path / "app/x.py").read_text()


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


def test_a_reexport_stays_even_when_the_file_has_other_fixes(repo):
    repo.write("helper.py", "# Here's the updated function\nfrom collections import OrderedDict\nprint(1)\n")
    repo.write("user.py", "from helper import OrderedDict\nprint(OrderedDict())\n")
    run_fix(repo)
    assert "OrderedDict" in (repo.path / "helper.py").read_text()


@pytest.mark.parametrize("source, other", [
    ("import json\nprint(1)\n", "import helper as h\nprint(h.json)\n"),
    ("import time\nprint(1)\n", "from unittest import mock\nimport helper\nmock.patch.object(helper, 'time')\n"),
    ("import json\nprint(1)\n", "import helper\nprint(getattr(helper, 'json'))\n"),
])
def test_other_routes_to_a_name_keep_it(repo, source, other):
    repo.write("helper.py", source)
    repo.write("user.py", other)
    run_fix(repo)
    assert (repo.path / "helper.py").read_text() == source


@pytest.mark.parametrize("source", [
    "import json\nprint(globals()['json'])\n",
    "import json\n\n\ndef f(x):\n    \"\"\"\n    >>> json.dumps(1)\n    '1'\n    \"\"\"\n    return x\n",
    "import typing\nx = []  # type: typing.List[int]\n",
    "import logging.handlers\nprint(1)\n",
])
def test_mentions_in_this_file_keep_an_import(repo, source):
    repo.write("app/x.py", source)
    run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source


def test_a_local_module_named_like_the_stdlib_keeps_its_import(repo):
    source = "import secrets\nprint(1)\n"
    repo.write("secrets.py", "print('side effect')\n")
    repo.write("app/x.py", source)
    run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source


def test_import_removal_is_opt_in(repo):
    source = "import os\nprint(1)\n"
    repo.write("app/x.py", source)
    repo.commit()
    repo.occam("fix", "--apply")
    assert (repo.path / "app/x.py").read_text() == source


def test_config_can_turn_fix_rules_off(repo):
    source = "# Here's the updated function\nx = 1\n"
    repo.write(".occam.json", '{"disable": ["ai-residue"]}')
    repo.write("app/x.py", source)
    repo.commit()
    repo.occam("fix", "--apply")
    assert (repo.path / "app/x.py").read_text() == source


def test_a_comment_with_a_reason_in_other_words_stays(repo):
    source = "# I've added a lock here as the pool deadlocks otherwise.\nx = 1\n"
    repo.write("app/x.py", source)
    run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source


def test_a_deep_expression_doesnt_abort_fix(repo):
    repo.write("app/deep.py", "# Here's the updated function\nx = " + "+".join(["1"] * 3000) + "\n")
    repo.write("app/x.py", "# Here's the updated function\ny = 1\n")
    done = run_fix(repo)
    assert "Traceback" not in done.stderr and done.returncode in (0, 1)


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


def test_ledger_next_needs_an_owner(repo):
    assert repo.occam("ledger", "next").returncode == 2


@pytest.mark.parametrize("line", ['API_KEY = "abc123def456ghi789"', 'DB = "postgres://admin:s3cr3tpw@db.internal/prod"', 'KEY = os.getenv("PAY_API_KEY", "pb_live_9f8e7d6c5b4a")'])
def test_secret_values_never_reach_saved_or_json_output(repo, tmp_path, line):
    repo.write("app/x.py", f"import os\n{line}\n")
    value = line.split('"')[-2] if "getenv" in line else line.split('"')[1]
    done = repo.occam("scan", "--format", "json", "--min-confidence", "low")
    assert value not in done.stdout
    saved = repo.occam("scan").stdout.split("Full results: ")[1].strip()
    assert value not in Path(saved).read_text()


def test_config_changes_dont_close_findings(repo):
    tracked(repo)
    repo.write(".occam.json", '{"disable": ["mutable-default"]}')
    assert "0 no longer present" in repo.occam("ledger", "sync").stdout
    repo.write(".occam.json", '{"ignore": ["app"]}')
    assert "0 no longer present" in repo.occam("ledger", "sync").stdout


def test_a_broken_neighbor_doesnt_close_cross_file_findings(repo):
    repo.write("app/lib.py", "def real():\n    return 1\n")
    repo.write("app/main.py", "from app.lib import missing\nprint(missing)\n")
    repo.commit()
    repo.occam("ledger", "sync")
    repo.write("app/lib.py", "def real(:\n")
    assert "0 no longer present" in repo.occam("ledger", "sync").stdout


def test_prefixes_of_flags_are_refused(repo):
    repo.write("app/x.py", "import os\nprint(1)\n")
    repo.commit()
    assert repo.occam("fix", "--app", "--rule", "unused-import").returncode == 2


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


def test_a_comment_above_a_coding_line_stays(repo):
    source = "# Here's the updated function\n# note\n# coding: latin-1\nx = 1\n"
    repo.write("app/x.py", source)
    done = run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source and "coding comment" in done.stdout


def test_computed_global_lookups_keep_imports(repo):
    source = "import json\nname = 'js' + 'on'\nprint(globals()[name])\n"
    repo.write("app/x.py", source)
    run_fix(repo)
    assert (repo.path / "app/x.py").read_text() == source
