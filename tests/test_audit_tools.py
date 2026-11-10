"""Things a fresh audit got these tools to say that weren't true. Each was reproduced before the fix."""

import stat
import sys
import time

import pytest
import test_tools

repo = test_tools.repo  # the shared fixture
sys.path.insert(0, str(test_tools.ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import files, manifests, verify, workflow  # noqa: E402
from occam_tools.zero_tests import ran_no_tests  # noqa: E402

PYTHON = sys.executable


def goal_with(repo, check):
    repo.occam("goal", "init", "x")
    return repo.occam("goal", "add", "works", "--check", check)


# ---- goal verify


@pytest.mark.parametrize("check", ["cd backend && pytest", "true || false", "echo pytest ; pytest", "pytest | tail -1", "pytest > out.txt"])
def test_a_check_written_as_shell_is_refused_rather_than_passing_without_running(repo, check):
    done = goal_with(repo, check)
    assert done.returncode == 2
    assert "sh -c" in done.stdout
    assert "R1" not in done.stdout


def test_a_recorded_check_written_as_shell_fails_at_verify(repo, monkeypatch, tmp_path):
    passed, said = workflow._run_check(tmp_path, "true && false", 5)
    assert passed is False
    assert "sh -c" in said


@pytest.mark.parametrize("check", ["sh -c 'cd app && false'", f"{PYTHON} -c 'print(1 and 2)'", f"{PYTHON} -c \"import sys; sys.exit(0)\""])
def test_shell_syntax_inside_quotes_isnt_refused(check):
    assert not workflow.needs_a_shell(check)


def test_a_wrapped_shell_check_really_runs(repo):
    repo.occam("goal", "init", "x")
    assert repo.occam("goal", "add", "works", "--check", "sh -c 'cd app && false'").returncode == 0
    done = repo.occam("goal", "verify")
    assert done.returncode != 0
    assert "ALL VERIFIED" not in done.stdout


def test_starting_a_goal_over_another_is_refused(repo):
    repo.occam("goal", "init", "first")
    repo.occam("goal", "add", "something", "--check", "true")
    done = repo.occam("goal", "init", "second")
    assert done.returncode == 2
    assert "first" in done.stdout
    assert "something" in repo.occam("goal", "status").stdout
    assert repo.occam("goal", "clear").returncode == 0
    assert repo.occam("goal", "init", "second").returncode == 0


@pytest.mark.parametrize("spelling", ["migrations/", "./migrations", "{root}/migrations", "migrations"])
def test_a_forbidden_folder_is_enforced_however_it_is_written(repo, spelling):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "constrain", "--forbid", spelling.format(root=repo.path))
    repo.write("migrations/a.sql", "select 1;\n")
    done = repo.occam("goal", "verify")
    assert "VIOLATED" in done.stdout
    assert done.returncode != 0


def test_a_scope_folder_is_understood_however_it_is_written(repo):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "scope", "./migrations")
    repo.write("migrations/a.sql", "select 1;\n")
    assert "DRIFT" not in repo.occam("goal", "verify").stdout


def test_a_goal_started_before_the_first_commit_still_sees_later_commits(tmp_path):
    path = tmp_path / "fresh"
    path.mkdir()
    made = test_tools.Repo(path, tmp_path / "state2")
    made.git("init", "-q")
    made.occam("goal", "init", "x")
    made.occam("goal", "constrain", "--forbid", "secret/")
    made.write("secret/a.txt", "x\n")
    made.git("add", "-A")
    made.git("commit", "-qm", "a")
    assert "VIOLATED" in made.occam("goal", "verify").stdout


def test_a_timed_out_check_stops_what_it_started(tmp_path):
    marker = tmp_path / "marker"
    script = tmp_path / "slow.sh"
    script.write_text(f"#!/bin/sh\n(sleep 1; touch {marker}) &\nwait\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    passed, said = workflow._run_check(tmp_path, str(script), 0)
    assert passed is False and "timed out" in said
    time.sleep(1.5)
    assert not marker.exists()


# ---- zero tests


@pytest.mark.parametrize("output", ["Executed 0 tests, with 0 failures", "0 tests, 0 failures", "DONE 0 tests in 0.1s", "0 pass\n0 fail", "# tests 0", "Tests:  0 passed, 0 total",
                                    "3 xfailed in 0.01s", "5 tests collected in 0.01s", "0 runs, 0 assertions, 0 failures"])
def test_more_ways_of_running_nothing_are_seen(output):
    assert ran_no_tests(output)


@pytest.mark.parametrize("output", ["jobs: 0 runs pending", "3 passed, 1 xfailed in 0.01s", "12 tests, 0 failures"])
def test_these_ran_something_or_arent_test_output(output):
    assert not ran_no_tests(output)


# ---- golden


def bytes_command(path, content):
    path.write_bytes(content)
    return ["cat", str(path)]


@pytest.mark.parametrize("before, after", [(b"a\xff\n", b"a\xfe\n"), (b"line\r\n", b"line\n")])
def test_golden_sees_changes_that_decoding_used_to_hide(repo, tmp_path, before, after):
    output = tmp_path / "output"
    assert repo.occam("golden", "record", "t", "--", *bytes_command(output, before)).returncode == 0
    output.write_bytes(after)
    done = repo.occam("golden", "check", "t")
    assert done.returncode == 1
    assert "CHANGED" in done.stdout


def test_golden_says_when_only_invisible_characters_changed(repo, tmp_path):
    output = tmp_path / "output"
    repo.occam("golden", "record", "t", "--", *bytes_command(output, b"line\r\n"))
    output.write_bytes(b"line\n")
    assert "invisible" in repo.occam("golden", "check", "t").stdout


def test_golden_warns_when_it_records_a_failure_and_when_that_still_matches(repo):
    recorded = repo.occam("golden", "record", "t", "--", PYTHON, "missing_script.py")
    assert "records a failure" in recorded.stdout
    checked = repo.occam("golden", "check", "t")
    assert checked.returncode == 0
    assert "doesn't show it works" in checked.stdout


def test_golden_warns_when_a_command_prints_nothing(repo):
    assert "prints nothing" in repo.occam("golden", "record", "t", "--", "true").stdout


# ---- mutate


def test_mutate_wont_score_tests_that_only_fail_on_their_second_run(repo):
    repo.write("app/add.py", "def add(a, b):\n    return a + b\n")
    repo.write("tests/test_add.py", "import os\nfrom app.add import add\n\n\ndef test_add():\n    os.mkdir('out')\n    add(1, 2)\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "add")
    done = repo.occam("mutate", "app/add.py", "--cmd", f"{PYTHON} -m pytest -q tests/test_add.py")
    assert done.returncode == 2, done.stdout
    assert "were caught" not in done.stdout
    assert "Nothing was measured" in done.stdout


def test_mutate_refuses_a_test_command_written_as_shell(repo):
    done = repo.occam("mutate", "app/core.py", "--cmd", "cd app && pytest")
    assert done.returncode == 2
    assert "sh -c" in done.stdout


def test_mutate_changed_finds_nothing_in_a_change_that_only_deleted_lines(repo):
    repo.write("app/del.py", "def keep(a):\n    # note\n    return a + 1\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "del")
    repo.write("app/del.py", "def keep(a):\n    return a + 1\n")
    done = repo.occam("mutate", "--changed", "--cmd", f"{PYTHON} -c pass")
    assert "were caught" not in done.stdout
    assert "No mutation points" in done.stdout


def test_mutate_changed_still_covers_a_new_untracked_file(repo):
    repo.write("app/new.py", "def more(a):\n    return a + 1\n")
    repo.write("tests/test_new.py", "from app.new import more\n\n\ndef test_more():\n    assert more(1) == 2\n")
    done = repo.occam("mutate", "--changed", "--cmd", f"{PYTHON} -m pytest -q tests/test_new.py")
    assert "were caught" in done.stdout, done.stdout


# ---- bench


@pytest.mark.parametrize("ys, low, high", [
    ([1.03, 2.02, 4.02], 0.8, 1.2),  # linear, no startup cost: read as n^2.94 before
    ([0.1, 0.2, 0.4, 0.8], 0.8, 1.2),  # read as n^1.41 before
    ([6, 7, 9, 13], 0.7, 1.24),  # linear, with startup
    ([1, 4, 16, 64], 1.8, 2.2),  # quadratic
    ([6, 9, 21, 69], 1.6, 2.4),  # quadratic, with startup
])
def test_growth_fits_with_or_without_a_startup_cost(ys, low, high):
    sizes = [1, 2, 4, 8][:len(ys)]
    assert low <= verify._slope(sizes, ys) <= high


def test_too_little_signal_still_says_so():
    assert verify._slope([1, 2, 4], [0.03, 0.03, 0.04]) is None


# ---- gate


def test_gate_doesnt_blame_a_change_for_an_import_that_was_already_broken(repo):
    repo.write("utils.py", "def something():\n    return 1\n")
    repo.write("legacy.py", "from utils import nothing_here\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "base")
    repo.write("utils.py", "def something():\n    return 1  # unrelated\n")
    assert "phantom-local-import" not in repo.occam("gate").stdout


def test_gate_still_blames_a_change_that_deletes_the_module_an_import_needs(repo):
    repo.write("gone.py", "def something():\n    return 1\n")
    repo.write("user.py", "import gone\n\ngone.something()\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "base")
    (repo.path / "gone.py").unlink()
    done = repo.occam("gate")
    assert done.returncode == 1
    assert "user.py" in done.stdout


def test_a_change_cant_clear_the_gate_by_editing_what_it_reads(repo):
    repo.write(".occam.json", '{"disable": ["dynamic-eval"]}\n')
    repo.write("app/core.py", "def total(a, b):\n    return eval(a)\n")
    done = repo.occam("gate")
    assert done.returncode == 1
    assert "gate-config-changed" in done.stdout or ".occam.json" in done.stdout


def test_gate_says_what_it_compared_and_mentions_committed_work(repo):
    done = repo.occam("gate")
    assert done.returncode == 0
    assert "compared with HEAD" in done.stdout and "--base" in done.stdout


def test_gate_naming_something_that_matches_nothing_isnt_clean(repo):
    repo.write(".gitignore", "gen/\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "ignore")
    repo.write("gen/x.py", "eval(input())\n")
    done = repo.occam("gate", "gen")
    assert done.returncode == 2
    assert "nothing was checked" in done.stdout


def test_gate_says_when_git_has_been_told_not_to_watch_a_file(repo):
    repo.git("update-index", "--skip-worktree", "app/core.py")
    repo.write("app/core.py", "eval(input())\n")
    assert "NOT CHECKED" in repo.occam("gate").stdout


def test_a_damaged_goal_store_doesnt_read_as_blockers(repo, tmp_path):
    repo.occam("goal", "init", "x")
    stores = list((tmp_path / "state").rglob("occam.db"))
    assert stores
    stores[0].write_bytes(b"this isn't a database" * 100)
    repo.write("app/core.py", "def total(a, b):\n    return a + b  # changed\n")
    done = repo.occam("gate")
    assert "Traceback" not in done.stderr
    assert done.returncode == 0


def test_a_conftest_that_stops_collection_is_a_blocker(repo):
    repo.write("tests/conftest.py", 'collect_ignore_glob = ["*"]\n')
    done = repo.occam("gate")
    assert done.returncode == 1
    assert "checks-hidden-by-config" in done.stdout or "leaves checks out" in done.stdout


# ---- fix


COMMENTED_OUT = "import os\n\n\ndef total():\n    return os.getcwd()\n\n\n# x = compute(1)\n# y = compute(2)\n# z = compute(3)\n"


# ---- names and roots


def test_git_names_that_leave_the_project_are_dropped(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("")
    (tmp_path / "secrets.py").write_text("")
    monkeypatch.setattr(files, "run_git", lambda *args, **kwargs: "a.py\0../secrets.py\0/etc/hosts\0")
    assert files.tracked_files(project) == ["a.py"]


def test_a_link_named_from_inside_a_project_doesnt_move_the_project(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.py").write_text("needle_outside = 1\n")
    (repo.path / "dirlink").symlink_to(outside)
    done = repo.occam("query", "grep", "needle_outside", "dirlink")
    assert "needle_outside =" not in done.stdout
    assert done.returncode == 2


def test_a_gitignore_further_up_doesnt_claim_a_plain_folder(tmp_path, monkeypatch):
    (tmp_path / ".gitignore").write_text("*.tmp\n")
    plain = tmp_path / "Downloads" / "tarball"
    plain.mkdir(parents=True)
    monkeypatch.chdir(plain)
    assert files.find_root(".") == plain.resolve()


def test_a_gitignore_in_the_folder_itself_still_marks_a_project(tmp_path, monkeypatch):
    plain = tmp_path / "project"
    plain.mkdir()
    (plain / ".gitignore").write_text("*.tmp\n")
    monkeypatch.chdir(plain)
    assert files.find_root(".") == plain.resolve()


# ---- ledger and crashes


def test_a_crash_doesnt_read_as_blockers(repo, monkeypatch, capsys):
    from occam_tools import cli, verify

    monkeypatch.setattr(verify, "gate", lambda *_, **__: 1 / 0)
    assert cli.main(["gate", "--root", str(repo.path)]) == 3
    assert "internal error" in capsys.readouterr().out


@pytest.mark.parametrize("line", ["#!/usr/bin/env sh", "#!/bin/sh", "#!/bin/dash", "#!/usr/bin/env dash", "#!/bin/ksh", "#!/bin/ash", "#!/bin/bash", "#!/usr/bin/env zsh"])
def test_the_scanner_and_query_agree_a_shell_shebang_is_shell(line):
    from occam_tools.source import language_of

    assert language_of("deploy", line + "\necho hi\n") == "shell"


# ---- a second fresh review, against the fixes above. Each of these regressed, or passed something real.


def plain_folder(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return test_tools.Repo(path, tmp_path / "state3")


def test_gate_root_through_a_link_checks_the_project_it_names(tmp_path):
    host = plain_folder(tmp_path, "host")
    host.git("init", "-q")
    host.write("a.txt", "a\n")
    host.commit("a")
    real = plain_folder(tmp_path, "proj_real")
    real.git("init", "-q")
    real.write("q.py", "x = 1\n")
    real.commit("q")
    real.write("q.py", "def f(a):\n    return eval(a)\n")
    (host.path / "current").symlink_to(real.path)
    done = host.occam("gate", "--root", "current")
    assert done.returncode == 1, done.stdout
    assert "No changes to gate" not in done.stdout


def test_a_link_named_from_outside_any_project_is_how_the_project_was_named(tmp_path):
    outside = plain_folder(tmp_path, "nowhere")
    real = plain_folder(tmp_path, "proj_real2")
    real.git("init", "-q")
    real.write("q.py", "def f(a):\n    return eval(a)\n")
    real.commit("q")
    (outside.path / "link").symlink_to(real.path)
    done = outside.occam("scan", "link")
    assert done.returncode != 2, done.stdout
    assert "outside this project" not in done.stdout


@pytest.mark.parametrize("name", ["app/lab_tests.py", "app/ab_tests.py", "scripts/run_tests.py", "app/tests.py"])
def test_a_name_that_says_tests_doesnt_lose_the_checks(repo, name):
    repo.write(name, 'DB_PASSWORD = "abc123xyz9"\n\n\ndef load(conn, name):\n    return conn.execute(f"SELECT * FROM users WHERE name = \'{name}\'")\n')
    done = repo.occam("gate")
    assert done.returncode == 1, done.stdout
    assert "hardcoded-secret" in repo.occam("scan", name).stdout or "sql-injection" in repo.occam("scan", name).stdout


@pytest.mark.parametrize("check", ['[ -n "$(cat missing_file_nope)" ]', 'test -n "$(pytest -q | grep passed)"', "test -n `false`", "true\nfalse", "echo a#b && false", "test -f f.fa # && false", "cd dir#1 && false", "test -n $HOME", 'test -n "$HOME"', "test -n ${HOME}"])
def test_shell_that_would_test_nothing_is_refused(check):
    assert workflow.needs_a_shell(check)


@pytest.mark.parametrize("check", ['grep -c ">" f.fa', r'find . -name "*.fa" -exec test -s {} \;', "grep -q '<' index.html", 'grep ";" f', 'grep "|" README', 'grep -q "&&" run.sh', 'pytest -k "a or b"',
                                   'pytest -k "not (a or b)"', 'python3 -c "print(1)"', 'python3 -c "print(2>1)"', "sh -c 'cd a && b'", "sh -c 'echo $HOME'", "grep -c '$(x)' f", "pytest -q tests/test_a.py"])
def test_ordinary_checks_arent_refused(check):
    assert not workflow.needs_a_shell(check)


def test_a_detached_child_holding_the_pipe_cant_outlast_the_limit(tmp_path):
    script = tmp_path / "loop.py"
    script.write_text("import subprocess, time\nsubprocess.Popen(['sleep', '20'], start_new_session=True)\ntime.sleep(100)\n")
    started = time.time()
    passed, said = workflow._run_check(tmp_path, f"{PYTHON} {script}", 1)
    assert passed is False and "timed out" in said
    assert time.time() - started < 8


def scan_rules(repo, name):
    return repo.occam("scan", name, "--min-confidence", "medium").stdout


@pytest.mark.parametrize("code, rule, reported", [
    ("import hashlib\n\n\ndef store(pwd):\n    return hashlib.md5(pwd.encode()).hexdigest()\n", "weak-password-hash", True),
    ("import hashlib\n\n\ndef cwd_key(pwd):\n    return hashlib.sha1(pwd.encode()).hexdigest()\n", "weak-password-hash", False),
    ('CLIENT = make("sk-0123456789abcdef0123456789abcdef")\n', "hardcoded-secret", True),
    ('client_secret = "Abc123.Def456"\n', "hardcoded-secret", True),
    ('REDIS_PASSWORD = "ADMIN_2024"\n', "hardcoded-secret", True),
    ('DB_PASSWORD = "Password123!"\n', "hardcoded-secret", True),
    ('SECRET_KEY = "secret-key-8f3a2b"\n', "hardcoded-secret", True),
    ('API_KEY = "test_abc123DEF456"\n', "hardcoded-secret", True),
    ('URL = "sk-learn-pipelines-and-column-transformers"\n', "hardcoded-secret", False),
    ('PASSWORD_ENV = "DB_PASSWORD_VALUE"\n', "hardcoded-secret", False),
    ('password = "password"\n', "hardcoded-secret", False),
    ("async def load(pool, x):\n    return await pool.fetch(f\"SELECT * FROM t WHERE a = '{x}'\")\n", "sql-injection", True),
    ("async def load(conn, x):\n    return await conn.fetchrow(f\"SELECT * FROM t WHERE a = '{x}'\")\n", "sql-injection", True),
    ('async def load(client, x):\n    return await client.fetch(f"https://example.com/{x}")\n', "sql-injection", False),
    ("def login(user, pw):\n    return True\n", "fake-success", True),
    ("def is_logged_in(req):\n    return True\n", "fake-success", True),
    ("def check_csrf(req):\n    return True\n", "fake-success", True),
    ("def verify_kw(*, token):\n    return True\n", "fake-success", True),
])
def test_what_the_scanner_reports(repo, code, rule, reported):
    repo.write("app/sample.py", code)
    assert (rule in scan_rules(repo, "app/sample.py")) is reported


@pytest.mark.parametrize("code", ['def process_payment(order):\n    pass\n\n\nROUTES = {"pay": process_payment}\n', "def deduct_balance(order):\n    pass\n\n\nregister(deduct_balance)\n"])
def test_a_stub_handed_to_something_still_blocks(repo, code):
    repo.write("app/pay.py", code)
    assert repo.occam("gate").returncode == 1


def test_a_signal_handler_meant_to_be_empty_doesnt_block(repo):
    repo.write("app/sig.py", "import signal\n\n\ndef on_sigterm(signum, frame):\n    pass\n\n\nsignal.signal(signal.SIGTERM, on_sigterm)\n")
    repo.write("tests/test_sig.py", "def test_x():\n    assert True is True\n")
    assert "stub-body" not in repo.occam("gate").stdout.split("Checks only you can make")[0].split("NOT READY")[0].replace("warning", "") or repo.occam("gate").returncode == 0


def test_gate_blocks_on_its_config_when_only_a_path_is_named(repo):
    repo.write(".occam.json", '{"disable": ["sql-injection"]}\n')
    repo.write("app/q.py", 'def f(conn, x):\n    return conn.execute(f"SELECT * FROM t WHERE a = {x}")\n')
    assert repo.occam("gate", "app/q.py").returncode == 1


def test_gate_blocks_on_its_config_when_git_is_told_to_ignore_it(repo):
    (repo.path / ".git" / "info" / "exclude").write_text(".occam.json\n")
    repo.write(".occam.json", '{"disable": ["sql-injection"]}\n')
    repo.write("app/q.py", 'def f(conn, x):\n    return conn.execute(f"SELECT * FROM t WHERE a = {x}")\n')
    assert repo.occam("gate").returncode == 1


def test_a_committed_config_doesnt_block(repo):
    repo.write(".occam.json", '{"disable": ["narration-comment"]}\n')
    repo.commit("config")
    repo.write("app/core.py", "def total(a, b):\n    return a + b + 0\n")
    assert "gate-config-changed" not in repo.occam("gate").stdout


@pytest.mark.parametrize("name", ["Pipfile", "setup.cfg", "environment.yml", "requirements-dev.in", "constraints.txt", "requirements/base.txt"])
def test_gate_notices_a_dependency_added_in_any_manifest_it_reads(repo, name):
    """The gate's own list of manifest names had drifted from the reader's, so these changed without a word."""
    repo.write(name, "[options]\ninstall_requires =\n    attrs\n" if name == "setup.cfg" else "attrs\n")
    repo.commit("manifest")
    repo.write(name, "[options]\ninstall_requires =\n    attrs\n    leftpad\n" if name == "setup.cfg" else "attrs\nleftpad\n")
    assert "This adds leftpad" in repo.occam("gate").stdout  # the gate's note, not the scanner's unused-dependency rule


def test_the_manifest_names_are_the_ones_read(tmp_path):
    named = ["pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "environment.yml", "environment.yaml", "conda.yaml", "package.json", "Cargo.toml", "go.mod",
             "requirements.txt", "dev-requirements.in", "constraints.txt", "requirements/base.txt", "sub/Pipfile",
             "Pipfile.lock", "requirements.md", "setup.cfg.bak", "tsconfig.json", "notes/constraints.md"]
    texts = {"pyproject.toml": '[project]\ndependencies = ["attrs"]\n', "setup.py": "setup(install_requires=['attrs'])\n", "setup.cfg": "[options]\ninstall_requires =\n    attrs\n",
             "package.json": '{"dependencies": {"attrs": "1"}}', "Cargo.toml": '[dependencies]\nattrs = "1"\n', "go.mod": "module m\nrequire example.com/attrs v1.0.0\n"}
    for name in named:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(texts.get(name.rsplit("/", 1)[-1], "attrs\n"))
    read = set(manifests.read_manifests(tmp_path, named)["files"]) - {"tsconfig.json"}  # aliases, not dependencies
    assert read == {name for name in named if manifests.DEPENDENCY_FILE.search(name)}


def test_a_moved_files_functions_arent_new(repo):
    """After `git mv`, the gate compared the moved file with nothing at its new path, so every function in it read as new and uncalled."""
    repo.write("app/extra.py", "def scale(x, k):\n    return x * k\n")
    repo.commit("extra")
    repo.git("mv", "app/extra.py", "app/moved.py")
    done = repo.occam("gate")
    assert "app/moved.py" in done.stdout or "1 changed" in done.stdout, done.stdout
    assert "New scale" not in done.stdout


@pytest.mark.parametrize("written", ['{"disable": ["narration-comment"]}\r\n', '﻿{"disable": ["narration-comment"]}\n'])
def test_a_committed_config_with_crlf_or_a_bom_doesnt_block_and_is_read(repo, written):
    """Git's copy had its line endings normalized and the disk copy its byte-order mark stripped, so every gate saw the config as changed."""
    (repo.path / ".occam.json").write_bytes(written.encode("utf-8"))
    repo.commit("config")
    repo.write("app/core.py", "def total(a, b):\n    return a + b + 0\n")
    assert "gate-config-changed" not in repo.occam("gate").stdout
    assert files.load_config(repo.path) == {"disable": ["narration-comment"]}


@pytest.mark.parametrize("spelling", ["./src/../migrations", "././migrations", "src/../migrations/"])
def test_more_spellings_of_a_forbidden_folder_are_enforced(repo, spelling):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "constrain", "--forbid", spelling)
    repo.write("migrations/1.sql", "select 1;\n")
    assert "VIOLATED" in repo.occam("goal", "verify").stdout


def test_a_dot_slash_forbid_means_from_where_it_was_typed(repo, tmp_path):
    (repo.path / "app").mkdir(exist_ok=True)
    inside = test_tools.Repo(repo.path / "app", tmp_path / "state")
    inside.occam("goal", "init", "x")
    inside.occam("goal", "constrain", "--forbid", "./gen")
    repo.write("app/gen/x.txt", "x\n")
    assert "VIOLATED" in repo.occam("goal", "verify").stdout


def test_a_globbed_forbid_still_works(repo):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "constrain", "--forbid", "migrations/*.sql")
    repo.write("migrations/1.sql", "select 1;\n")
    assert "VIOLATED" in repo.occam("goal", "verify").stdout


def test_blank_lines_dont_make_the_zero_test_check_slow():
    started = time.time()
    assert not ran_no_tests("\n" * 32000)
    assert time.time() - started < 1


@pytest.mark.parametrize("output, expected", [("0 features passed, 0 failed, 0 skipped", True), ("0 scenarios", True), ("0 specs, 0 failures", True), ("checked 12 files, 0 tests, 0 failures in legacy", False)])
def test_more_zero_test_forms(output, expected):
    assert ran_no_tests(output) is expected


def test_a_goal_store_of_the_wrong_shape_doesnt_read_as_blockers(repo, tmp_path):
    import sqlite3

    repo.occam("goal", "init", "x")
    store = next((tmp_path / "state").rglob("occam.db"))
    with sqlite3.connect(store) as db:
        db.execute("UPDATE kv SET value = '[]' WHERE key = 'goal'")
    repo.write("app/core.py", "def total(a, b):\n    return a + b  # changed\n")
    assert repo.occam("gate").returncode == 0


def test_removing_a_re_export_is_this_changes_fault(repo):
    repo.write("pkg/__init__.py", "from .inner import helper\n")
    repo.write("pkg/inner.py", "def helper():\n    return 1\n")
    repo.write("user.py", "from pkg import helper\n\nprint(helper())\n")
    repo.commit("base")
    repo.write("pkg/__init__.py", "\n")
    assert repo.occam("gate").returncode == 1


@pytest.mark.parametrize("line", ["collect_ignore: List[str] = ['x']", "collect_ignore_glob: list = ['*']", "collect_ignore.append('x')"])
def test_annotated_collect_ignore_is_seen(repo, line):
    repo.write("tests/conftest.py", line + "\n")
    assert repo.occam("gate").returncode == 1


@pytest.mark.parametrize("header", ["# Generated by Cursor for our Django app", "# Generated with ChatGPT using the openapi spec"])
def test_saying_an_assistant_wrote_it_doesnt_mark_it_generated(repo, header):
    repo.write("app/made.py", header + "\n\n\ndef f(a):\n    return eval(a)\n")
    assert "dynamic-eval" in repo.occam("scan", "app/made.py").stdout


@pytest.mark.parametrize("header", ["# Generated by Django 4.2 on 2026-01-01", "# Generated by the protoc compiler", "// Code generated by mockgen. DO NOT EDIT."])
def test_a_real_generator_header_still_marks_it_generated(repo, header):
    repo.write("app/made.py", header + "\n\n\ndef f(a):\n    return eval(a)\n")
    assert "dynamic-eval" not in repo.occam("scan", "app/made.py").stdout


@pytest.mark.parametrize("path, blocked", [("app/billing.py", True), ("app/auth/session.py", True), ("app/report_format.py", False)])
def test_a_security_or_money_change_without_a_test_blocks_the_gate(repo, path, blocked):
    """The owner chose on 2026-11-08: where a fresh reviewer is needed, a change no test came with blocks; elsewhere it warns."""
    repo.write(path, "def total(a, b):\n    return a + b\n")
    repo.commit("add")
    repo.write(path, "def total(a, b):\n    return a + b + 1\n")
    done = repo.occam("gate")
    assert "module-untested" in done.stdout and (done.returncode == 1) == blocked, done.stdout
    repo.write("tests/test_total.py", "from app import billing\n\n\ndef test_total():\n    assert billing.total(1, 2) == 4\n")
    assert "module-untested" not in repo.occam("gate").stdout


def test_the_gate_and_the_hooks_agree_on_security_and_money_paths():
    sys.path.insert(0, str(test_tools.ROOT / "plugin" / "hooks"))
    import classify
    words = ["auth", "oauth", "login", "session", "sessions", "token", "password", "secret", "credential", "permission", "acl", "rbac", "tenant", "tenancy",
             "crypto", "signature", "billing", "payment", "invoice", "checkout", "refund", "ledger", "migrations", "webhook", "author", "authors", "admin",
             "tokenizer", "report", "Auth", "BILLING", "payments_v2", "x"]
    shapes = ["{w}.py", "app/{w}/x.py", "src/{w}_service.ts", "lib/x-{w}.go", "pkg/{w}.rs", "{w}s/y.rb", "x{w}.py", "a/{w}"]
    for path in (shape.format(w=word) for word in words for shape in shapes):
        hooks_say = bool(classify.SECURITY_CRITICAL.search(path) or classify.MONEY.search(path))
        assert bool(verify._SECURITY_OR_MONEY.search(path)) == hooks_say, path
