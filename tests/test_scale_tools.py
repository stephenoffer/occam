"""Occam's tools on a very large repository: they answer in time, say what they didn't read, and find what they always found when nothing limits them."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import cli, files as filesystem, inventory, scan as scanner, verify  # noqa: E402


# ---------------------------------------------------------------- a very large repository

sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))


def small_repo(root: Path, count: int = 12) -> Path:
    for index in range(count):
        folder = root / ("a" if index % 2 else "b")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"m{index}.py").write_text(f"def helper_{index}(value):\n    return value + {index}\n")
    return root


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("OCCAM_STATE_DIR", str(tmp_path / "occam-state"))
    return tmp_path / "occam-state"


def cached_rows(state_dir: Path) -> int:
    import sqlite3
    connection = sqlite3.connect(str(state_dir / "cache.db"))
    try:
        return connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    finally:
        connection.close()


def test_a_scan_killed_partway_keeps_what_it_finished(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "_BATCH_FILES", 4)
    analyze, seen = scanner._analyze_for_pool, []

    def killed_on_the_tenth(item):
        seen.append(item)
        if len(seen) == 10:
            raise KeyboardInterrupt  # what a shell tool's timeout looks like from inside
        return analyze(item)

    monkeypatch.setattr(scanner, "_analyze_for_pool", killed_on_the_tenth)
    with pytest.raises(KeyboardInterrupt):
        scanner.run_scan(repo, workers=1)
    assert cached_rows(state) == 8, "two whole batches finished, so a retry doesn't start over"


def test_running_out_of_time_returns_what_was_read_and_says_so(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "_BATCH_FILES", 4)
    analyze = scanner._analyze_for_pool

    def slow(item):
        time.sleep(0.3)
        return analyze(item)

    monkeypatch.setattr(scanner, "_analyze_for_pool", slow)
    result = scanner.run_scan(repo, workers=1, seconds=1)
    partial = result.stats["partial"]
    assert partial["reason"] == "time" and partial["read"] == 4 and partial["wanted"] == 12
    assert result.stats["analyzed"] == 4


def test_the_next_run_gets_further_and_cross_file_rules_return_when_it_all_fits(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "_BATCH_FILES", 4)
    analyze = scanner._analyze_for_pool

    def slow(item):
        time.sleep(0.3)
        return analyze(item)

    monkeypatch.setattr(scanner, "_analyze_for_pool", slow)
    assert "unreferenced-def" not in {f["rule"] for f in scanner.run_scan(repo, workers=1, seconds=1).findings}, "its callers may be in what wasn't read"
    assert cached_rows(state) == 4
    scanner.run_scan(repo, workers=1, seconds=1)
    assert cached_rows(state) == 8
    monkeypatch.setattr(scanner, "_analyze_for_pool", analyze)
    final = scanner.run_scan(repo, workers=1, seconds=60)
    assert final.stats["partial"] is None
    assert "unreferenced-def" in {f["rule"] for f in final.findings}


def test_a_scan_with_time_to_spare_finds_exactly_what_an_unlimited_one_does(tmp_path, state):
    repo = small_repo(tmp_path / "repo", 40)
    (repo / "a" / "bad.py").write_text("import nonexistent_thing\n\ndef stub():\n    pass\n")
    limited = scanner.run_scan(repo, seconds=60)
    unlimited = scanner.run_scan(repo, use_cache=False)
    assert limited.stats["partial"] is None
    assert sorted(f["id"] for f in limited.findings) == sorted(f["id"] for f in unlimited.findings)
    assert sorted(f["id"] for f in limited.findings), "a comparison of nothing shows nothing"


def test_on_a_very_large_repository_a_scoped_scan_reads_only_its_scope(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    result = scanner.run_scan(repo, [str(repo / "a")], seconds=60)
    assert set(result.project.files) == {f"a/m{i}.py" for i in range(1, 12, 2)}
    partial = result.stats["partial"]
    assert partial["reason"] == "scope" and partial["repository_files"] == 12 and partial["read"] == 6


def test_cross_file_rules_cannot_call_things_unused_because_of_what_was_not_read(tmp_path, state, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "a").mkdir(parents=True)
    (repo / "b").mkdir()
    (repo / "a" / "lib.py").write_text("def used_elsewhere(value):\n    return value\n")
    (repo / "b" / "app.py").write_text("from a.lib import used_elsewhere\nprint(used_elsewhere(1))\n")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 1)
    rules = {f["rule"] for f in scanner.run_scan(repo, [str(repo / "a")], seconds=60).findings}
    assert not rules & {"orphan-module", "unused-function", "unreferenced-def", "dead-code"}


def test_without_a_time_limit_a_scoped_scan_still_reads_everything(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    result = scanner.run_scan(repo, [str(repo / "a")])
    assert len(result.project.files) == 12 and result.stats["partial"] is None


def test_time_runs_out_on_the_most_changed_files_last(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    monkeypatch.setattr(scanner, "_BATCH_FILES", 2)
    monkeypatch.setattr(filesystem, "churn", lambda root, commits=3000, timeout=120: {"b/m10.py": 9, "a/m3.py": 5})
    analyze = scanner._analyze_for_pool

    def slow(item):
        time.sleep(0.6)
        return analyze(item)

    monkeypatch.setattr(scanner, "_analyze_for_pool", slow)
    assert set(scanner.run_scan(repo, workers=1, seconds=1).project.languages) == {"b/m10.py", "a/m3.py"}


def test_partial_results_lead_the_report(tmp_path, state, monkeypatch):
    from occam_tools import report
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    result = scanner.run_scan(repo, [str(repo / "a")], seconds=60)
    text = report.render_text(result.findings, 0, result.stats, 30)
    assert text.split("\n")[1].startswith("PARTIAL: this repository has 12 files"), "agents pipe this through head"
    assert "--max-seconds 0" in text


@pytest.mark.parametrize("arguments, expected", [(["scan"], scanner.DEFAULT_SECONDS), (["scan", "--max-seconds", "5"], 5), (["scan", "--max-seconds", "0"], None), (["map"], scanner.DEFAULT_SECONDS),
                                                 (["gate"], scanner.DEFAULT_SECONDS), (["deps"], scanner.DEFAULT_SECONDS), (["partition"], scanner.DEFAULT_SECONDS)])
def test_commands_an_agent_runs_are_limited_by_default(arguments, expected):
    assert cli._time_limit(cli._parser().parse_args(arguments)) == expected


@pytest.mark.parametrize("flags", [["--fail-on", "high"], ["--new-only"], ["--baseline", "x"], ["--format", "sarif"]])
def test_a_scan_something_else_decides_on_stays_complete_unless_asked(tmp_path, state, monkeypatch, flags):
    repo = small_repo(tmp_path / "repo")
    seen = {}
    real = scanner.run_scan

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(scanner, "run_scan", spy)
    monkeypatch.chdir(repo)
    assert cli.main(["scan", *flags]) in (0, 1)
    assert seen["seconds"] is None


def test_a_repository_too_large_to_scan_gets_a_table_of_contents(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    monkeypatch.setattr(scanner, "run_scan", lambda *args, **kwargs: pytest.fail("nothing should be read"))
    data = inventory.build_map(repo, None, False, 90)
    assert data["estimated"] and {row["path"] for row in data["folders"]} == {"a/", "b/"} and data["files"] == 12
    text = inventory.render_map(data)
    for needed in ("about", "a/", "occam map FOLDER", "occam scan FOLDER", "occam gate", "--max-seconds 0", "no file was read"):
        assert needed in text


def test_the_table_descends_past_a_folder_with_only_one_child(tmp_path, state, monkeypatch):
    repo = tmp_path / "repo"
    small_repo(repo / "src" / "main")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    data = inventory.build_map(repo, None, False, 90)
    assert {row["path"] for row in data["folders"]} == {"src/main/a/", "src/main/b/"}


def test_mapping_a_folder_that_is_itself_too_large_lists_inside_it(tmp_path, state, monkeypatch):
    repo = tmp_path / "repo"
    small_repo(repo / "big" / "x")
    small_repo(repo / "big" / "y")
    (repo / "other.py").write_text("x = 1\n")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    data = inventory.build_map(repo, repo / "big", False, 90)
    assert {row["path"] for row in data["folders"]} == {"big/x/", "big/y/"}


def test_mapping_a_small_folder_of_a_large_repository_plans_it(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo", 60)
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 40)
    data = inventory.build_map(repo, repo / "a", False, 90)
    assert "estimated" not in data and data["files"] == 30
    assert inventory.render_map(data).split("\n")[2].startswith("PARTIAL")


def test_partition_says_to_choose_folders_when_there_are_too_many_files(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    plan = inventory.partition(repo, None, seconds=60)
    assert plan["agents"] == 0 and "occam map" in plan["reason"]
    assert "occam map" in inventory.render_partition(plan)


def git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=repo, check=True, capture_output=True)


def committed_repo(root: Path) -> Path:
    small_repo(root)
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-qm", "start")
    return root


def test_gate_on_a_very_large_repository_reads_only_the_change_and_says_what_it_missed(tmp_path, state, monkeypatch):
    repo = committed_repo(tmp_path / "repo")
    (repo / "a" / "m1.py").write_text("def helper_1(value):\n    return value + 2\n\ndef brand_new(value):\n    return value\n")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    read = []
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (read.append(item[0]), real(item))[1])
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 10**9)
    text, _ = verify.gate(repo, seconds=60)
    assert read == ["a/m1.py"]
    assert "PARTIAL" in text.split("\n")[1]
    assert "has no callers" not in text, "its callers may be in what wasn't read"


def test_gate_on_an_ordinary_repository_still_sees_the_whole_picture(tmp_path, state):
    repo = committed_repo(tmp_path / "repo")
    (repo / "a" / "m1.py").write_text("def helper_1(value):\n    return value + 2\n\ndef brand_new(value):\n    return value\n")
    text, _ = verify.gate(repo, seconds=60)
    assert "PARTIAL" not in text
    assert "brand_new has no callers" in text


def test_a_parallel_scan_puts_the_working_directory_back(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 2)
    monkeypatch.chdir(tmp_path)
    assert scanner.run_scan(repo, workers=2).stats["analyzed"] == 12
    assert Path.cwd() == tmp_path.resolve()


def test_workers_that_cannot_start_fall_back_to_this_process(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 2)

    def broken(*args, **kwargs):
        raise OSError("no more processes")

    monkeypatch.setattr(scanner, "ProcessPoolExecutor", broken)
    monkeypatch.chdir(tmp_path)
    assert scanner.run_scan(repo, workers=2).stats["analyzed"] == 12
    assert Path.cwd() == tmp_path.resolve()


def test_map_of_a_tiny_program_does_not_ask_for_a_reviewer(tmp_path, state):
    (tmp_path / "hello.py").write_text('print("hello world")\n')
    data = inventory.build_map(tmp_path, None, False, 90)
    assert data["tier"] == "cell" and data["agents"]["fresh_reviewers"] == 0 and data["agents"]["readers_for_audit"] == 0
    assert "No plan file and no subagents" in inventory.render_map(data)


def test_map_of_a_small_repository_still_asks_for_a_reviewer(tmp_path, state):
    small_repo(tmp_path, 40)
    assert inventory.build_map(tmp_path, None, False, 90)["agents"]["fresh_reviewers"] == 1


def test_focus_cannot_read_what_the_scan_leaves_out(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.py").write_text("def merge_lists():\n    return 1\n")
    (repo / "b" / "real.py").write_text("def merge_lists():\n    return 2\n")
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 10**9)
    read = []
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (read.append(item[0]), real(item))[1])
    scanner.run_scan(repo, seconds=60, focus=["node_modules/dep.py", "b/real.py"], use_cache=False)
    assert "node_modules/dep.py" not in read and read[0] == "b/real.py", "named first, and nothing outside the scan"
    read.clear()
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    result = scanner.run_scan(repo, seconds=60, focus=["node_modules/dep.py", "b/real.py"], use_cache=False)
    assert read == ["b/real.py"] and result.stats["partial"]["reason"] == "scope"


def duplicated_repo(root: Path) -> Path:
    body = "".join(f"def fn_{i}(value):\n    total = value + {i}\n    total = total * 2\n    total = total - 1\n    total = total + 3\n    total = total * 5\n    return total\n\n" for i in range(6))
    for name in ("a/one.py", "z/two.py"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(body)
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n")
    return root


def ids(result):
    return sorted(f["id"] for f in result.findings)


@pytest.mark.parametrize("name, rule", [(".env", "committed-secret-file"), ("id_rsa", "committed-secret-file")])
def test_gate_on_a_very_large_repository_still_stops_a_committed_secret_file(tmp_path, state, monkeypatch, name, rule):
    repo = committed_repo(tmp_path / "repo")
    (repo / name).write_text("KEY=value\n")
    git(repo, "add", name)
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    text, code = verify.gate(repo, seconds=60)
    assert code == 1 and rule in text and "PARTIAL" in text


def test_a_batch_stops_at_a_byte_limit_as_well_as_a_file_limit(tmp_path, monkeypatch):
    for index in range(6):
        (tmp_path / f"m{index}.py").write_text("x" * 100)
    names = [f"m{index}.py" for index in range(6)]
    monkeypatch.setattr(scanner, "_BATCH_BYTES", 250)
    assert [len(batch) for batch in scanner._batches(tmp_path, names)] == [3, 3]
    monkeypatch.setattr(scanner, "_BATCH_BYTES", 10**9)
    monkeypatch.setattr(scanner, "_BATCH_FILES", 4)
    assert [len(batch) for batch in scanner._batches(tmp_path, names)] == [4, 2]
    assert [path for batch in scanner._batches(tmp_path, [*names, "missing.py"]) for path in batch] == [*names, "missing.py"]


def spying_on_scan(monkeypatch):
    seen = {}
    real = scanner.run_scan

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(scanner, "run_scan", spy)
    return seen


@pytest.mark.parametrize("arguments", [["map"], ["scan"], ["deps"], ["partition"], ["gate", "a/m1.py"]])
def test_each_command_really_passes_its_limit_to_the_scan(tmp_path, state, monkeypatch, capsys, arguments):
    repo = small_repo(tmp_path / "repo")
    seen = spying_on_scan(monkeypatch)
    monkeypatch.chdir(repo)
    cli.main(arguments)
    capsys.readouterr()
    assert seen["seconds"] == scanner.DEFAULT_SECONDS


@pytest.mark.parametrize("arguments", [["baseline", "write", "--out", "b.json"]])
def test_commands_needing_a_complete_answer_have_no_limit(tmp_path, state, monkeypatch, capsys, arguments):
    repo = small_repo(tmp_path / "repo")
    seen = spying_on_scan(monkeypatch)
    monkeypatch.chdir(repo)
    cli.main(arguments)
    capsys.readouterr()
    assert not seen.get("seconds")


def test_a_negative_limit_is_refused(capsys):
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["scan", "--max-seconds", "-1"])
    capsys.readouterr()


def slowed(monkeypatch, delay=0.3):
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (time.sleep(delay), real(item))[1])
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 10**9)
    monkeypatch.setattr(scanner, "_BATCH_FILES", 4)


def test_partition_on_too_little_of_a_repository_gives_no_plan(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    slowed(monkeypatch)
    plan = inventory.partition(repo, None, seconds=1)
    assert plan["agents"] == 0 and plan["shards"] == [] and plan["partial"]["read"] == 4
    text = inventory.render_partition(plan)
    assert "PARTIAL" in text and "You can read this yourself" not in text and "no honest plan" in text


def test_map_of_a_repository_it_could_not_finish_doesnt_describe_it_from_what_it_reached(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n")
    slowed(monkeypatch)
    data = inventory.build_map(repo, None, False, 1)
    assert data["estimated"] and data["ran_out"] and data["files"] == 13
    text = inventory.render_map(data)
    assert "couldn't be read and checked within 1s" in text and "Tests: 0 files" not in text


def test_map_of_a_folder_still_finds_the_manifest_above_it(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo", 60)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n[tool.ruff]\n')
    (repo / "package.json").write_text('{"name": "x"}\n')
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 40)
    data = inventory.build_map(repo, repo / "a", False, 90)
    assert "PARTIAL" in inventory.render_map(data)
    assert {"pyproject.toml", "package.json"} <= set(data["manifests"])
    assert "ruff" in data["configured_tools"]


def test_a_read_that_finished_too_late_says_that_and_not_files_not_reached(tmp_path, state, monkeypatch):
    from occam_tools import report
    repo = small_repo(tmp_path / "repo", 4)
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (time.sleep(0.2), real(item))[1])
    result = scanner.run_scan(repo, workers=1, seconds=1)
    assert result.stats["partial"]["read"] == result.stats["partial"]["wanted"] == 4
    note = report.partial_note(result.stats)[0]
    assert "read all 4 files" in note and "not reached" not in note


def test_without_a_cache_the_note_does_not_promise_progress(tmp_path, state, monkeypatch):
    from occam_tools import report
    repo = small_repo(tmp_path / "repo")
    slowed(monkeypatch)
    assert "saved" not in report.partial_note(scanner.run_scan(repo, workers=1, seconds=1, use_cache=False).stats)[0]


def test_gate_on_a_deletion_stays_narrow_too(tmp_path, state, monkeypatch):
    repo = committed_repo(tmp_path / "repo")
    (repo / "a" / "m1.py").unlink()
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 10**9)
    read = []
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (read.append(item[0]), real(item))[1])
    text, _ = verify.gate(repo, seconds=60)
    assert read == [] and "PARTIAL" in text


@pytest.mark.parametrize("workers", [1, 2])
def test_the_scan_itself_does_not_need_a_working_directory(tmp_path, state, monkeypatch, workers):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 2)

    def gone():
        raise FileNotFoundError("the working directory has been deleted")

    monkeypatch.setattr(os, "getcwd", gone)
    assert scanner.run_scan(repo, workers=workers).stats["analyzed"] == 12


def test_a_sarif_scan_with_a_limit_says_partial_somewhere_a_person_can_see(tmp_path, state, monkeypatch, capsys):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    monkeypatch.chdir(repo)
    cli.main(["scan", "a", "--format", "sarif", "--max-seconds", "60"])
    assert "PARTIAL" in capsys.readouterr().err


def test_deps_on_a_very_large_repository_reads_nothing_it_could_not_use(tmp_path, state, monkeypatch):
    from occam_tools import depcheck
    repo = small_repo(tmp_path / "repo")
    (repo / "requirements.txt").write_text("requests\n")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 10**9)
    read = []
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (read.append(item[0]), real(item))[1])
    text, _ = depcheck.report(repo, seconds=60)
    assert read == [] and "PARTIAL" in text and "requirements.txt" in text


def test_deps_on_an_ordinary_repository_still_checks_use(tmp_path, state):
    from occam_tools import depcheck
    repo = small_repo(tmp_path / "repo")
    (repo / "requirements.txt").write_text("requests\n")
    text, _ = depcheck.report(repo, seconds=60)
    assert "PARTIAL" not in text and "unused-dependency" in text


def test_a_cache_past_its_limit_loses_its_oldest_half_and_keeps_working(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    scanner.run_scan(repo, workers=1)
    assert cached_rows(state) == 12
    monkeypatch.setattr(scanner, "_MAX_CACHE_BYTES", 1)
    scanner.Cache(state).close()
    assert cached_rows(state) == 6
    monkeypatch.setattr(scanner, "_MAX_CACHE_BYTES", 2_000_000_000)
    assert scanner.run_scan(repo, workers=1).stats["analyzed"] == 12
    assert cached_rows(state) == 12


def test_a_partial_read_never_claims_writers_are_independent(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo", 20)
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 15)
    plan = inventory.partition(repo, [str(repo / "a")], reader_budget=1, mode="write", seconds=60)
    assert plan["agents"] == 1 and len(plan["shards"]) == 1, "these share no imports, and a whole read would call them independent"
    assert len(inventory.partition(repo, [str(repo / "a")], reader_budget=1, mode="write")["shards"]) > 1


def test_a_partial_write_plan_for_a_folder_with_no_code_says_there_is_none(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo", 20)
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("x\n")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 15)
    plan = inventory.partition(repo, [str(repo / "docs")], mode="write", seconds=60)
    assert plan["agents"] == 0 and plan["shards"] == []


def test_gate_cannot_call_something_orphaned_because_of_what_it_did_not_read(tmp_path, state, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "lib").mkdir(parents=True)
    (repo / "one").mkdir()
    (repo / "two").mkdir()
    (repo / "lib" / "tools.py").write_text("def shared_thing(value):\n    return value\n")
    (repo / "one" / "caller.py").write_text("from lib.tools import shared_thing\n\nprint(shared_thing(1))\n")
    (repo / "two" / "other.py").write_text("from lib.tools import shared_thing\n\nprint(shared_thing(2))\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "start")
    (repo / "one" / "caller.py").write_text("print(1)\n")
    (repo / "two" / "other.py").write_text("print(2)\n")
    (repo / "lib" / "tools.py").write_text("def shared_thing(value):\n    return value + 1\n")
    both_gone, _ = verify.gate(repo, seconds=60)
    assert "orphaned-by-change" in both_gone, "with the whole picture, removing the last callers is reported"
    git(repo, "checkout", "--", "two/other.py")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 2)
    text, _ = verify.gate(repo, seconds=60)
    assert "orphaned-by-change" not in text and "PARTIAL" in text, "two/other.py still calls it, and this read didn't see that"


def test_a_scoped_scan_credits_a_duplicate_to_the_same_file_however_it_was_read(tmp_path, state):
    repo = duplicated_repo(tmp_path / "repo")
    plain = scanner.run_scan(repo, [str(repo / "z")], use_cache=False)
    assert ids(scanner.run_scan(repo, [str(repo / "z")], seconds=60, use_cache=False)) == ids(plain)
    assert ids(scanner.run_scan(repo, [str(repo / "z")], focus=["z/two.py"], use_cache=False)) == ids(plain)
    assert ids(scanner.run_scan(repo, None, focus=["z/two.py"], use_cache=False)) == ids(scanner.run_scan(repo, None, use_cache=False))


def test_gate_does_not_blame_a_change_for_old_duplicates_it_read_first(tmp_path, state):
    repo = duplicated_repo(tmp_path / "repo")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "start")
    (repo / "z" / "two.py").write_text((repo / "z" / "two.py").read_text() + "VALUE = 1\n")
    text, code = verify.gate(repo, seconds=60)
    assert "clone-block" not in text and "clone-function" not in text and code == 0, text


def test_a_scan_of_the_whole_tree_by_name_is_not_scoped(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    result = scanner.run_scan(repo, [str(repo)], seconds=60)
    assert result.stats["partial"] is None and "unreferenced-def" in {f["rule"] for f in result.findings}


def test_a_committed_secret_file_nothing_read_yet_is_still_named(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo")
    (repo / "z").mkdir()
    (repo / "z" / ".env").write_text("KEY=value\n")
    (repo / "z" / "id_rsa").write_text("x\n")
    monkeypatch.setattr(scanner, "_BATCH_FILES", 1)
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (time.sleep(1.2), real(item))[1])
    result = scanner.run_scan(repo, workers=1, seconds=1, focus=["a/m1.py"])
    assert result.stats["partial"]["read"] == 1, "only what was named first was read, so the secret files weren't"
    assert {("committed-secret-file", "z/.env"), ("committed-secret-file", "z/id_rsa")} <= {(f["rule"], f["path"]) for f in result.findings}


def test_isolated_keeps_its_meaning_under_a_limit(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo", 20)
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    result = scanner.run_scan(repo, [str(repo / "a")], isolated=True, seconds=60)
    assert result.stats["isolated"] and result.stats["partial"] is None, "it asked for this, so it isn't a narrowing to report"
    assert set(result.project.files) == {f"a/m{i}.py" for i in range(1, 20, 2)}


def test_isolated_read_that_finished_late_is_complete_for_what_it_asked(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo", 4)
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (time.sleep(0.2), real(item))[1])
    assert scanner.run_scan(repo, [str(repo / "a")], isolated=True, workers=1, seconds=1).stats["partial"] is None


def test_map_with_isolated_reads_the_large_folder_it_was_told_to(tmp_path, state, monkeypatch):
    repo = small_repo(tmp_path / "repo", 20)
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    assert "estimated" not in inventory.build_map(repo, repo / "a", True, 60)
    assert inventory.build_map(repo, repo / "a", False, 60)["estimated"]


@pytest.mark.parametrize("how", [signal.SIGKILL, signal.SIGTERM])
def test_workers_do_not_outlive_a_killed_scan(tmp_path, state, how):
    """A shell tool's timeout kills the scan. Before this, its workers stayed forever at about 40 MB each."""
    repo = small_repo(tmp_path / "repo", 4000)
    scan = subprocess.Popen([sys.executable, str(ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam.py"), "scan", "--workers", "2", str(repo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "OCCAM_STATE_DIR": str(state)})
    children: list[str] = []
    deadline = time.monotonic() + 20
    while len(children) < 2 and time.monotonic() < deadline and scan.poll() is None:
        children = subprocess.run(["pgrep", "-P", str(scan.pid)], capture_output=True, text=True).stdout.split()
        time.sleep(0.05)
    if scan.poll() is not None:
        pytest.skip("the scan finished before it could be killed")
    os.kill(scan.pid, how)
    scan.wait()
    deadline = time.monotonic() + 15
    alive = children
    while alive and time.monotonic() < deadline:
        alive = [pid for pid in alive if subprocess.run(["ps", "-p", pid, "-o", "pid="], capture_output=True).returncode == 0]
        time.sleep(0.2)
    assert not alive


def test_a_slow_git_costs_map_one_line_says_so_and_is_asked_for_an_answer_in_time(tmp_path, state, monkeypatch):
    repo = committed_repo(tmp_path / "repo")
    asked = []

    def no_answer(root, timeout=120):
        asked.append(timeout)
        raise filesystem.GitProblem("git status failed here, so changes can't be determined")

    monkeypatch.setattr(filesystem, "dirty_paths", no_answer)
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    table = inventory.build_map(repo, None, False, 60)
    assert table["estimated"] and "unknown, because git didn't answer" in inventory.render_map(table)
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 50_000)
    plan = inventory.build_map(repo, None, False, 60)
    assert "estimated" not in plan and "unknown, because git didn't answer" in inventory.render_map(plan)
    assert set(asked) == {inventory.GIT_SECONDS}


def test_without_a_limit_a_git_that_failed_is_still_an_error(tmp_path, state, monkeypatch):
    repo = committed_repo(tmp_path / "repo")

    def no_answer(root, timeout=120):
        raise filesystem.GitProblem("git status failed here, so changes can't be determined")

    monkeypatch.setattr(filesystem, "dirty_paths", no_answer)
    with pytest.raises(filesystem.GitProblem):
        inventory.build_map(repo, None, False, None)


def test_a_broken_repository_is_not_reported_as_having_nothing_uncommitted(tmp_path, state):
    repo = committed_repo(tmp_path / "repo")
    (repo / "new.py").write_text("x = 1\n")
    (repo / ".git" / "config").write_text("[this is not a config file\n")
    with pytest.raises(filesystem.GitProblem):
        filesystem.dirty_paths(repo)
    assert "unknown, because git didn't answer" in inventory.render_map(inventory.build_map(repo, None, False, 60))


def test_a_command_that_cannot_finish_says_so_before_a_shell_tool_would_kill_it(tmp_path, state, monkeypatch, capsys):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "GRACE_SECONDS", 0)
    real = filesystem.run_git

    def slow(*args, **kwargs):
        time.sleep(30)
        return real(*args, **kwargs)

    monkeypatch.setattr(filesystem, "run_git", slow)
    started = time.monotonic()
    assert cli.main(["gate", "--max-seconds", "1"]) == 2
    assert time.monotonic() - started < 5
    assert "didn't finish in 1s" in capsys.readouterr().out


def test_the_hard_stop_is_disarmed_when_a_command_returns(tmp_path, state, monkeypatch, capsys):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    assert cli.main(["scan", "--max-seconds", "60"]) == 0
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    capsys.readouterr()


def test_a_stuck_worker_cannot_keep_a_stopped_scan_waiting(tmp_path, monkeypatch):
    """A running chunk would otherwise hold the pool's shutdown to its end, and a truly hung file never ends."""
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 1)
    monkeypatch.chdir(tmp_path)
    started = None
    with pytest.raises(cli._OutOfTime):
        with scanner._Workers(2) as workers:
            workers.analyze([("a.py", "x = 1\\n")])
            processes = list(workers.pool._processes.values())
            stuck = workers.pool.submit(time.sleep, 60)
            while not stuck.running():  # one still queued would just be cancelled, and nothing would be stuck
                time.sleep(0.01)
            time.sleep(1)
            started = time.monotonic()
            raise cli._OutOfTime
    assert time.monotonic() - started < 5
    deadline = time.monotonic() + 10
    while any(process.is_alive() for process in processes) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not any(process.is_alive() for process in processes)
    assert Path.cwd() == tmp_path.resolve()


def test_tolerant_code_cannot_swallow_the_hard_stop(tmp_path, state, monkeypatch, capsys):
    """`_analyze_for_pool` catches Exception so one strange file can't stop a scan. That mustn't stop this."""
    repo = small_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "GRACE_SECONDS", 0)
    monkeypatch.setattr(scanner, "analyze_text", lambda *args, **kwargs: time.sleep(30))
    started = time.monotonic()
    assert cli.main(["scan", "--workers", "1", "--max-seconds", "1"]) == 2
    assert time.monotonic() - started < 5
    capsys.readouterr()


def test_no_limit_means_no_hard_stop(tmp_path, state, monkeypatch, capsys):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    assert cli.main(["scan", "--max-seconds", "0"]) == 0
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    capsys.readouterr()


def slow_reading(monkeypatch):
    real = scanner._analyze_for_pool
    monkeypatch.setattr(scanner, "_analyze_for_pool", lambda item: (time.sleep(0.3), real(item))[1])
    monkeypatch.setattr(scanner, "_PARALLEL_FROM", 10**9)
    monkeypatch.setattr(scanner, "_BATCH_FILES", 4)


def test_gate_strict_does_not_pass_changed_files_it_did_not_reach(tmp_path, state, monkeypatch):
    repo = committed_repo(tmp_path / "repo")
    for index in range(1, 12, 2):
        name = f"a/m{index}.py"
        (repo / name).write_text((repo / name).read_text() + "VALUE = 2\n")
    monkeypatch.setattr(verify, "_gate_extras", lambda *args, **kwargs: {"warnings": [], "others": ""})
    slow_reading(monkeypatch)
    text, code = verify.gate(repo, strict=True, seconds=1)  # first, because what this reads is saved and the next run would finish
    assert code == 1 and "NOT CHECKED" in text


def test_gate_strict_is_not_failed_by_unchanged_files_it_did_not_reach(tmp_path, state, monkeypatch):
    repo = committed_repo(tmp_path / "repo")
    (repo / "a" / "m1.py").write_text((repo / "a" / "m1.py").read_text() + "VALUE = 2\n")
    monkeypatch.setattr(verify, "_gate_extras", lambda *args, **kwargs: {"warnings": [], "others": ""})
    slow_reading(monkeypatch)
    text, code = verify.gate(repo, strict=True, seconds=1)
    assert code == 0 and "PARTIAL" in text


def test_gate_strict_can_pass_a_scope_it_read_in_full(tmp_path, state, monkeypatch):
    """Otherwise a repository past 50,000 files could never pass, and CI would stay red for nothing it could fix."""
    repo = committed_repo(tmp_path / "repo")
    (repo / "a" / "m1.py").write_text((repo / "a" / "m1.py").read_text() + "VALUE = 2\n")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    monkeypatch.setattr(verify, "_gate_extras", lambda *args, **kwargs: {"warnings": [], "others": ""})
    text, code = verify.gate(repo, strict=True, seconds=60)
    assert code == 0 and "PARTIAL" in text


def test_gate_strict_reads_everything_unless_told_otherwise():
    assert cli._time_limit(cli._parser().parse_args(["gate", "--strict"])) is None
    assert cli._time_limit(cli._parser().parse_args(["gate", "--strict", "--max-seconds", "9"])) == 9


def test_fail_on_with_a_limit_does_not_pass_what_it_did_not_read(tmp_path, state, monkeypatch, capsys):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "GRACE_SECONDS", 30)
    slow_reading(monkeypatch)
    assert cli.main(["scan", "--fail-on", "critical", "--max-seconds", "1", "--workers", "1"]) == 1
    assert "PARTIAL" in capsys.readouterr().out


def test_fail_on_is_not_failed_by_files_outside_its_scope(tmp_path, state, monkeypatch, capsys):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "GRACE_SECONDS", 30)
    slow_reading(monkeypatch)
    assert cli.main(["scan", "a/m1.py", "--fail-on", "critical", "--max-seconds", "1", "--workers", "1"]) == 0
    assert "PARTIAL" in capsys.readouterr().out


def test_fail_on_with_a_limit_can_pass_a_scope_it_read_in_full(tmp_path, state, monkeypatch, capsys):
    repo = small_repo(tmp_path / "repo")
    monkeypatch.setattr(scanner, "LARGE_REPOSITORY_FILES", 5)
    monkeypatch.chdir(repo)
    assert cli.main(["scan", "a", "--fail-on", "critical", "--max-seconds", "60"]) == 0
    assert "PARTIAL" in capsys.readouterr().out


def test_coord_status_still_answers_when_git_cannot(tmp_path, state, monkeypatch, capsys):
    repo = committed_repo(tmp_path / "repo")
    (repo / ".git" / "config").write_text("[this is not a config file\n")
    monkeypatch.chdir(repo)
    assert cli.main(["coord", "status", "--root", str(repo)]) == 0
    assert "uncommitted work is unknown" in capsys.readouterr().out


def test_a_folder_that_has_gone_gets_a_sentence_and_not_a_traceback(tmp_path, state):
    repo = small_repo(tmp_path / "repo")
    tool = ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam.py"
    script = f'mkdir gone && cd gone && rmdir ../gone && "{sys.executable}" "{tool}" scan "{repo}"'
    done = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=60, env={**os.environ, "OCCAM_STATE_DIR": str(state)})
    assert "Traceback" not in done.stderr and done.returncode == 2 and "no longer exists" in done.stdout


WORKER_THAT_REPORTS_ITSELF = """
import multiprocessing, os, sys, time
sys.path.insert(0, sys.argv[2])
from concurrent.futures import ProcessPoolExecutor
from occam_tools import scan
if __name__ == "__main__":
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context(sys.argv[1]), initializer=scan._exit_with_parent)
    print(pool.submit(os.getpid).result(timeout=60), flush=True)
    time.sleep(120)
"""


@pytest.mark.parametrize("method", ["spawn", "forkserver"])
def test_a_worker_goes_when_the_scan_is_killed_whichever_way_it_started(tmp_path, method):
    """Under forkserver the worker's parent is the fork server, which outlives the scan."""
    import multiprocessing
    if method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"no {method} here")
    script = tmp_path / "scan_like.py"
    script.write_text(WORKER_THAT_REPORTS_ITSELF)
    scan_like = subprocess.Popen([sys.executable, str(script), method, str(ROOT / "plugin" / "skills" / "occam" / "scripts")], stdout=subprocess.PIPE, text=True, cwd=tmp_path)
    worker = scan_like.stdout.readline().strip()
    assert worker.isdigit()
    os.kill(scan_like.pid, signal.SIGKILL)
    scan_like.wait()
    deadline = time.monotonic() + 15
    while subprocess.run(["ps", "-p", worker, "-o", "pid="], capture_output=True).returncode == 0 and time.monotonic() < deadline:
        time.sleep(0.2)
    assert subprocess.run(["ps", "-p", worker, "-o", "pid="], capture_output=True).returncode != 0


@pytest.mark.parametrize("method", ["spawn", "forkserver"])
def test_watching_for_a_gone_parent_does_not_end_a_healthy_worker(method):
    """Under forkserver, Linux's default on Python 3.14, a worker's parent is the fork server and not the scan."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    if method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"no {method} here")
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context(method), initializer=scanner._exit_with_parent) as pool:
        future = pool.submit(os.getpid)
        assert future.result(timeout=30) > 0
        time.sleep(2.5)  # the watcher looks once a second, so a wrong answer would have ended it by now
        assert pool.submit(os.getpid).result(timeout=30) == future.result()
