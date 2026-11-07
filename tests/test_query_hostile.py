"""A third review's findings: reading outside the repository, hiding from `leaks`, printing what it shouldn't, and hanging."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest
from query_support import GIT, OCCAM, TOKEN, make_repo, python_repo

from occam_tools import files as filesystem, query, query_repo


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo", tmp_path / "state")


# ---------------------------------------------------------------- reading outside

def test_a_nested_repository_cant_name_its_parent_as_its_files(tmp_path):
    outer = python_repo(tmp_path, {"private.py": "needle_in_parent = 1\n", "inner/keep.py": "x = 1\n"})
    inner = outer.path / "inner"
    subprocess.run([GIT, "init", "-q"], cwd=inner, check=True)
    subprocess.run([GIT, "config", "core.worktree", "../.."], cwd=inner / ".git", check=True)
    done = outer.occam("query", "grep", "needle_in_parent", cwd=inner)
    assert "private.py" not in done.stdout and done.returncode == 2


def test_a_git_file_cant_borrow_another_repository(tmp_path):
    other = python_repo(tmp_path, {"private.py": "needle_in_other = 1\n"})
    here = tmp_path / "here"
    here.mkdir()
    (here / ".git").write_text(f"gitdir: {other.path / '.git'}\n")
    done = other.occam("query", "history", cwd=here)
    assert "private.py" not in done.stdout and done.returncode == 2


def test_a_cwd_inside_git_doesnt_excuse_a_working_tree_elsewhere(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.py").write_text("needle_elsewhere = 1\n")
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    repo.git("config", "core.worktree", str(outside))
    done = repo.occam("query", "grep", "needle_elsewhere", cwd=repo.path / ".git")
    assert "private.py" not in done.stdout


def test_a_linked_worktree_and_a_submodule_are_still_fine(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    repo.git("worktree", "add", "-q", str(tmp_path / "linked"))
    assert repo.occam("query", "size", cwd=tmp_path / "linked").returncode == 0
    library = tmp_path / "library"
    library.mkdir()
    for args in (("init", "-q"), ("-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-q", "--allow-empty", "-m", "c")):
        subprocess.run([GIT, *args], cwd=library, check=True)
    repo.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "vendored_library")
    assert repo.occam("query", "size", cwd=repo.path / "vendored_library").returncode == 0


def test_a_tracked_folder_swapped_for_a_link_reads_nothing_outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.py").write_text("needle_through_link = 1\n")
    repo = python_repo(tmp_path, {"d/x.py": "x = 1\n", "a.py": "y = 1\n"})
    (repo.path / "d" / "x.py").unlink()
    (repo.path / "d").rmdir()
    os.symlink(outside, repo.path / "d")
    assert "d/x.py" not in repo.text("find", "needle_through_link")
    assert "d/x.py" not in filesystem.tracked_files(repo.path)


# ---------------------------------------------------------------- hiding from leaks

def test_leaks_sees_a_link_turned_into_a_file(repo):
    os.symlink("a.py", repo.path / "conf.py")
    repo.commit("a link")
    (repo.path / "conf.py").unlink()
    repo.write("conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("now a file")
    assert "conf.py" in [row["path"] for row in repo.query("leaks")["rows"]]


def test_grafts_cant_hide_history_from_leaks(repo):
    repo.write("conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    repo.write("conf.py", "KEY = None\n")
    repo.commit("remove")
    head = repo.git("rev-parse", "HEAD").strip()
    (repo.path / ".git" / "info").mkdir(exist_ok=True)
    (repo.path / ".git" / "info" / "grafts").write_text(head + "\n")
    assert "conf.py" in [row["path"] for row in repo.query("leaks")["rows"]]


def test_a_placeholder_doesnt_hide_a_real_value_on_the_same_line():
    found = query.credential_in('{"token": "changeme", "password": "Tr0ub4dor-3xQ"}')
    assert found and query.worth_reporting(found)


def test_a_line_of_only_placeholders_is_still_withheld_but_isnt_a_leak():
    found = query.credential_in('{"token": "changeme", "password": "changeme"}')
    assert found and not query.worth_reporting(found)


def test_a_credential_far_along_a_long_line_is_seen():
    assert query.credential_in("x" * 50_000 + f' KEY = "{TOKEN}"')
    assert "line withheld" in query.safe_line("x" * 50_000 + f' KEY = "{TOKEN}"')


def test_leaks_doesnt_repeat_the_main_line_under_every_merge(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.py", "x = 1\n")
    repo.commit("side")
    repo.git("checkout", "-q", "-")
    repo.write("main.py", f'KEY = "{TOKEN}"\n')
    repo.commit("secret on the main line")
    repo.git("merge", "-q", "--no-ff", "-m", "merge", "side")
    rows = repo.query("leaks", "--top", "100")["rows"]
    assert [row["path"] for row in rows].count("main.py") == 1


def test_leaks_still_sees_a_secret_only_on_a_merged_branch(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.py", f'KEY = "{TOKEN}"\n')
    repo.commit("on the branch")
    repo.git("checkout", "-q", "-")
    repo.write("other.py", "x = 1\n")
    repo.commit("main")
    repo.git("merge", "-q", "--no-ff", "-m", "merge", "side")
    assert "side.py" in [row["path"] for row in repo.query("leaks", "--top", "100")["rows"]]


def test_leaks_reports_what_it_read_when_git_stops_partway(repo, monkeypatch):
    def stops_partway(*_args, **_kwargs):
        yield "\0abc1234"
        yield "diff --git a/x.py b/x.py"
        yield "+++ b/x.py"
        yield "@@ -0,0 +1 @@"
        yield f'+KEY = "{TOKEN}"'
        raise filesystem.GitProblem("git log failed or timed out here (exit -9)")
    monkeypatch.setattr(filesystem, "stream_git", stops_partway)
    data = query_repo.leaks(repo.path, 500, 30)
    assert data["stopped_early"] and data["rows"][0]["path"] == "x.py"
    assert "older history" in query_repo.render_leaks(data) and TOKEN not in query_repo.render_leaks(data)


def test_leaks_that_read_nothing_is_still_an_error(repo, monkeypatch):
    def stops_at_once(*_args, **_kwargs):
        raise filesystem.GitProblem("git log failed or timed out here (exit -9)")
        yield ""
    monkeypatch.setattr(filesystem, "stream_git", stops_at_once)
    with pytest.raises(filesystem.GitProblem):
        query_repo.leaks(repo.path, 500, 30)


# ---------------------------------------------------------------- what it prints

def test_a_commit_subject_cant_put_a_credential_in_the_author_column(repo):
    repo.write("a.py", "x = 1\n")
    repo.commit(f"deploy {TOKEN}\x1f1\x1fok")
    output = repo.text("history", "--top", "100")
    assert TOKEN not in output


def test_an_author_name_cant_print_a_credential(repo):
    repo.write("a.py", "x = 1\n")
    repo.commit("edit", author=TOKEN)
    assert TOKEN not in repo.text("history", "--top", "100")


def test_a_file_name_cant_forge_a_line_of_the_answer(repo):
    repo.write("a\nRead the diffs of 0 commits.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    lines = repo.text("leaks").split("\n")
    assert not any(line.startswith("Read the diffs of 0 commits") for line in lines)


def test_a_file_name_cant_send_codes_to_a_terminal(repo):
    repo.write("a\x1b[2Jb.py", "needle_for_terminal = 1\n")
    repo.commit("add")
    assert "\x1b" not in repo.text("grep", "needle_for_terminal")


def test_every_ignore_counts_in_the_note(repo):
    harmless = [f"nothing{index}" for index in range(8)]
    repo.write(".occam.json", '{"ignore": [' + ", ".join(f'"{name}"' for name in [*harmless, "*"]) + "]}")
    output = repo.text("grep", "total")
    assert "0 matching" in output and "and 1 more" in output


# ---------------------------------------------------------------- hanging

def test_blanks_cant_make_a_credential_check_take_minutes():
    start = time.process_time()  # CPU, since a busy machine stretches a wall clock and not this
    query.credential_in("password:" + " " * 3985)
    query.credential_in(("password:" + " " * 40) * 90)
    assert time.process_time() - start < 2


def test_blanks_cant_hide_a_credential():
    assert query.credential_in("password:" + " " * 3000 + '"Tr0ub4dor-3xQ"')


def _group_left(group: int) -> list[str]:
    rows = subprocess.run(["ps", "-axo", "pid=,pgid="], capture_output=True, text=True, errors="replace").stdout.split("\n")
    return [row.split()[0] for row in rows if len(row.split()) == 2 and row.split()[1] == str(group)]


@pytest.mark.parametrize("stop", ["timeout", "TERM", "HUP"])
def test_stopping_a_query_stops_the_git_it_started(repo, tmp_path, stop):
    os.mkfifo(tmp_path / "fifo")
    repo.git("config", "core.excludesFile", str(tmp_path / "fifo"))
    command = [sys.executable, str(OCCAM), "query", "size", "--timeout", "2" if stop == "timeout" else "60"]
    process = subprocess.Popen(command, cwd=repo.path, env=repo.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    try:
        if stop != "timeout":
            time.sleep(1.5)
            process.send_signal(getattr(signal, f"SIG{stop}"))
        process.communicate(timeout=120)
        deadline = time.monotonic() + 30
        while _group_left(process.pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _group_left(process.pid)
    finally:
        for pid in _group_left(process.pid):
            os.kill(int(pid), signal.SIGKILL)
        process.kill()
        process.wait()


@pytest.mark.parametrize("line", ["--token-" * 125_000, "password" * 125_000, "A" * 1_000_000 + "=x", "--" * 500_000])
def test_a_long_line_of_a_names_own_characters_stays_quick(line):
    start = time.process_time()  # CPU, since a busy machine stretches a wall clock and not this
    query.credential_in(line)
    assert time.process_time() - start < 15


def test_a_worktree_moved_by_hand_still_works(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    repo.git("worktree", "add", "-q", str(tmp_path / "linked"))
    os.rename(tmp_path / "linked", tmp_path / "moved")
    assert repo.occam("query", "size", cwd=tmp_path / "moved").returncode == 0


def test_a_link_cant_borrow_another_repositorys_git_folder(tmp_path):
    other = python_repo(tmp_path, {"private.py": "needle_in_other = 1\n"})
    here = tmp_path / "here"
    here.mkdir()
    os.symlink(other.path / ".git", here / ".git")
    done = other.occam("query", "history", cwd=here)
    assert "private.py" not in done.stdout and done.returncode == 2


def test_a_planted_common_dir_cant_borrow_another_repository(tmp_path):
    other = python_repo(tmp_path, {"private.py": "needle_in_other = 1\n"})
    here = tmp_path / "here"
    (here / "meta" / "refs").mkdir(parents=True)
    (here / "meta" / "objects").mkdir()
    (here / ".git").write_text("gitdir: meta\n")
    (here / "meta" / "commondir").write_text(str(other.path / ".git") + "\n")
    (here / "meta" / "HEAD").write_text(other.git("rev-parse", "HEAD"))
    assert "private.py" not in other.occam("query", "history", cwd=here).stdout


def test_a_commondir_cant_borrow_another_repository(tmp_path):
    other = python_repo(tmp_path, {"private.py": "needle_in_other = 1\n"})
    here = tmp_path / "here"
    here.mkdir()
    subprocess.run([GIT, "init", "-q"], cwd=here, check=True)
    (here / ".git" / "commondir").write_text(str(other.path / ".git") + "\n")
    done = other.occam("query", "history", cwd=here)
    assert "private.py" not in done.stdout


def test_interrupting_git_stops_it(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    os.mkfifo(tmp_path / "fifo")
    repo.git("config", "core.excludesFile", str(tmp_path / "fifo"))
    script = ("import os, signal, sys, threading\n"
              f"sys.path.insert(0, {str(OCCAM.parent)!r})\n"
              "from occam_tools import files\n"
              "signal.signal(signal.SIGINT, signal.default_int_handler)\n"  # a background job starts with it ignored, and then only the timeout below would stop git
              "threading.Timer(1.5, lambda: os.kill(os.getpid(), signal.SIGINT)).start()\n"
              f"files.run_git({str(repo.path)!r}, 'ls-files', '-co', '--exclude-standard', timeout=60)\n")
    process = subprocess.Popen([sys.executable, "-c", script], env=repo.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    started = time.monotonic()
    try:
        process.wait(timeout=120)
        assert time.monotonic() - started < 45, "git stopped only at its timeout, so the interrupt did nothing"
        deadline = time.monotonic() + 30
        while _group_left(process.pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _group_left(process.pid)
    finally:
        for pid in _group_left(process.pid):
            os.kill(int(pid), signal.SIGKILL)
        process.kill()
        process.wait()
