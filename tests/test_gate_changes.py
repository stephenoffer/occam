"""`gate` sees what a commit would contain, and tells a test that moved from one that went away."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest
from query_support import OCCAM, TOKEN, python_repo

TWO = "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n"
ONE = "def test_a():\n    assert 1\n"
BAD = f'def f(items=[]):\n    return eval(items)\nKEY = "{TOKEN}"\n'


@pytest.fixture
def repo(tmp_path):
    return python_repo(tmp_path, {"app.py": "def f():\n    return 1\n", "0.txt": "x\n", "tests/test_core.py": TWO})


def _weakened(repo) -> str:
    done = repo.occam("gate")
    return done.stdout if "test-weakened" in done.stdout else ""


def test_a_carriage_return_cant_hide_the_next_file(repo):
    repo.write("0.txt", "x \r@@ -0,0 +1,100000 @@\n")
    repo.write("b.py", "y = 1\n")
    repo.commit("add")
    repo.write("0.txt", "x \r@@ -0,0 +1,100000 @@\nmore\n")
    repo.write("b.py", BAD)
    done = repo.occam("gate", "--strict")
    assert done.returncode == 1 and "b.py" in done.stdout


def test_a_test_removed_only_in_the_index_is_seen(repo):
    repo.write("tests/test_core.py", ONE)
    repo.git("add", "tests/test_core.py")
    repo.write("tests/test_core.py", TWO)
    done = repo.occam("gate")
    assert done.returncode == 1 and "test_b" in done.stdout


def test_marking_a_file_unchanged_doesnt_hide_what_is_staged(repo):
    repo.write("conf.py", "x = 1\n")
    repo.commit("add")
    repo.write("conf.py", f'KEY = "{TOKEN}"\n')
    repo.git("add", "conf.py")
    repo.write("conf.py", "x = 1\n")
    repo.git("update-index", "--assume-unchanged", "conf.py")
    assert repo.occam("gate").returncode == 1


def test_a_move_whose_destination_isnt_staged_is_still_a_removal(repo):
    repo.write("tests/test_core.py", ONE)
    repo.git("add", "tests/test_core.py")
    repo.write("tests/test_core.py", TWO)
    repo.write("tests/test_more.py", "def test_b():\n    assert 2\n")
    assert "test_b" in _weakened(repo)


def test_a_staged_move_with_its_destination_staged_is_fine(repo):
    repo.write("tests/test_core.py", ONE)
    repo.write("tests/test_more.py", "def test_b():\n    assert 2\n")
    repo.git("add", "tests/test_core.py", "tests/test_more.py")
    repo.write("tests/test_core.py", ONE + "\n\ndef test_c():\n    assert 3\n")
    assert _weakened(repo) == ""


def test_a_test_file_swapped_for_a_link_is_seen(repo):
    (repo.path / "tests" / "test_core.py").unlink()
    repo.write("tests/empty.py", "")
    os.symlink("empty.py", repo.path / "tests" / "test_core.py")
    assert "test_core.py" in _weakened(repo)


def test_a_test_file_padded_past_the_read_limit_is_seen(repo):
    repo.write("tests/test_core.py", "# padding\n" * 300_000)
    assert "test_core.py" in _weakened(repo)


def test_an_old_finding_in_a_partly_staged_file_doesnt_block(repo):
    repo.write("old.py", "def f(items=[]):\n    return items\n")
    repo.commit("old")
    repo.write("old.py", "def f(items=[]):\n    return items\n\n\nA = 1\n")
    repo.git("add", "old.py")
    repo.write("old.py", "def f(items=[]):\n    return items\n\n\nA = 1\nB = 2\n")
    assert "In the staged version" not in repo.occam("gate").stdout


@pytest.mark.parametrize("name, content", [
    ("tests/test_core.py", ONE + "\n\ndef helper():\n    def test_b():\n        assert 2\n"),
    ("tests/test_core.py", ONE + "\n\nif False:\n    def test_b():\n        assert 2\n"),
    ("tests/test_core.py", ONE + "\n\nclass Checks:\n    def test_b(self):\n        assert 2\n"),
])
def test_a_test_pytest_wont_collect_counts_as_removed(repo, name, content):
    repo.write(name, content)
    assert "test_b" in _weakened(repo)


@pytest.mark.parametrize("destination, content", [
    ("tests/.attic/test_more.py", "def test_b():\n    assert 2\n"),
    ("tests/test_more.py", "__test__ = False\n\n\ndef test_b():\n    assert 2\n"),
    ("tests/more_checks.py", "def test_b():\n    assert 2\n"),
])
def test_a_move_to_where_pytest_wont_look_counts_as_removed(repo, destination, content):
    repo.write("tests/test_core.py", ONE)
    repo.write(destination, content)
    assert "test_b" in _weakened(repo)


def test_renaming_a_test_file_so_pytest_wont_collect_it_is_seen(repo):
    repo.git("mv", "tests/test_core.py", "tests/core_checks.py")
    assert "core_checks" in _weakened(repo)


def test_renaming_a_test_file_out_of_the_tests_is_seen(repo):
    repo.git("mv", "tests/test_core.py", "core.py")
    assert "core.py" in _weakened(repo)


def test_an_honest_split_may_delete_the_original(repo):
    repo.git("rm", "-q", "tests/test_core.py")
    repo.write("tests/test_one.py", "def test_a():\n    assert 1\n")
    repo.write("tests/test_two.py", "def test_b():\n    assert 2\n")
    assert _weakened(repo) == ""


def test_deleting_a_test_file_still_blocks_when_its_tests_went_with_it(repo):
    repo.git("rm", "-q", "tests/test_core.py")
    repo.write("tests/test_one.py", "def test_a():\n    assert 1\n")
    assert "test_b" in _weakened(repo)


def test_moving_a_fixture_named_like_a_test_removes_nothing(repo):
    fixture = "import pytest\n\n\n@pytest.fixture\ndef test_user():\n    return 1\n"
    repo.write("tests/test_user.py", fixture + "\n\ndef test_c(test_user):\n    assert test_user\n")
    repo.commit("fixture")
    repo.write("tests/test_user.py", "def test_c(test_user):\n    assert test_user\n")
    repo.write("tests/conftest.py", fixture)
    assert _weakened(repo) == ""


@pytest.mark.parametrize("line", ['@pytest.mark.skipif(True, reason="x")\ndef test_c():\n    assert 3\n', '@pytest.mark.skip\ndef test_c():\n    assert 3\n', 'pytest.importorskip("numpy")\n', '@pytest.mark.xfail\ndef test_c():\n    assert 3\n'])
def test_every_way_of_not_running_a_test_counts_as_a_skip(repo, line):
    repo.write("tests/test_core.py", "import pytest\n\n\n" + TWO)
    repo.commit("import")
    repo.write("tests/test_core.py", "import pytest\n\n\n" + TWO + "\n\n" + line)
    assert "new skips" in _weakened(repo)


def test_deleting_a_comment_cant_cancel_a_real_skip(repo):
    repo.write("tests/test_core.py", "import pytest\n\n# we used to skip these\n" + TWO)
    repo.commit("comment")
    repo.write("tests/test_core.py", "import pytest\n\n" + TWO + "\n\n@pytest.mark.skip\ndef test_c():\n    assert 3\n")
    assert "new skips" in _weakened(repo)


def test_a_word_in_a_string_isnt_a_skip(repo):
    repo.write("tests/test_core.py", TWO + '\n\ndef test_c():\n    assert "skip" != "xfail"\n')
    assert _weakened(repo) == ""


def test_two_classes_can_hold_a_test_with_the_same_name(repo):
    both = "class TestA:\n    def test_run(self):\n        assert 1\n\n\nclass TestB:\n    def test_run(self):\n        assert 2\n"
    repo.write("tests/test_classes.py", both)
    repo.commit("classes")
    repo.write("tests/test_classes.py", "class TestB:\n    def test_run(self):\n        assert 2\n")
    assert "TestA.test_run" in _weakened(repo)


# ---------------------------------------------------------------- what narrowing the check got wrong, per a review of it

@pytest.mark.parametrize("decorated", ['@pytest.mark.usefixtures("db")\ndef test_c():\n    assert 3\n', '@patch("app.fixtures.load")\ndef test_c(load):\n    assert 3\n'])
def test_a_decorator_mentioning_fixtures_doesnt_make_a_test_a_fixture(repo, decorated):
    repo.write("tests/test_core.py", TWO + "\n\n" + decorated)
    repo.commit("more")
    repo.write("tests/test_core.py", TWO)
    assert "test_c" in _weakened(repo)


@pytest.mark.parametrize("before", ["class Checks(MyBase):\n    def test_c(self):\n        assert 3\n", "class TestOuter:\n    class TestInner:\n        def test_c(self):\n            assert 3\n"])
def test_a_test_in_a_class_with_a_base_or_nested_counts(repo, before):
    repo.write("tests/test_core.py", TWO + "\n\n" + before)
    repo.commit("more")
    repo.write("tests/test_core.py", TWO)
    assert "test_c" in _weakened(repo)


def test_a_file_named_only_like_a_test_isnt_where_tests_can_move(repo):
    repo.write("tests/test_core.py", ONE)
    repo.write("tests/testhelpers.py", "def test_b():\n    assert 2\n")
    assert "test_b" in _weakened(repo)


def test_a_variable_named_skipped_isnt_a_skip(repo):
    repo.write("tests/test_core.py", TWO + "\n\ndef test_c():\n    skipped = []\n    assert not skipped\n")
    assert _weakened(repo) == ""


def test_renaming_a_class_keeps_its_tests(repo):
    repo.write("tests/test_classes.py", "class TestOld:\n    def test_run(self):\n        assert 1\n")
    repo.commit("class")
    repo.write("tests/test_classes.py", "class TestNew:\n    def test_run(self):\n        assert 1\n")
    assert _weakened(repo) == ""


def test_renaming_a_helper_with_no_tests_removes_nothing(repo):
    repo.write("tests/test_helpers.py", "def build():\n    return 1\n")
    repo.commit("helper")
    repo.git("mv", "tests/test_helpers.py", "tests/helpers.py")
    assert _weakened(repo) == ""


def test_stopping_gate_stops_the_git_it_started(repo, tmp_path):
    os.mkfifo(tmp_path / "fifo")
    repo.git("config", "core.excludesFile", str(tmp_path / "fifo"))
    process = subprocess.Popen([sys.executable, str(OCCAM), "gate"], cwd=repo.path, env=repo.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    left = lambda: [row.split()[0] for row in subprocess.run(["ps", "-axo", "pid=,pgid="], capture_output=True, text=True, errors="replace").stdout.split("\n") if len(row.split()) == 2 and row.split()[1] == str(process.pid)]  # noqa: E731
    try:
        time.sleep(1.5)
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=120)
        deadline = time.monotonic() + 30
        while left() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not left()
    finally:
        for pid in left():
            os.kill(int(pid), signal.SIGKILL)
        process.kill()
        process.wait()


def test_a_base_of_object_doesnt_make_a_class_collected(repo):
    repo.write("tests/test_classes.py", "class TestFoo:\n    def test_c(self):\n        assert 3\n")
    repo.commit("class")
    repo.write("tests/test_classes.py", "class Foo(object):\n    def test_c(self):\n        assert 3\n")
    assert "test_c" in _weakened(repo)


def test_two_renamed_classes_are_compared_with_their_own_tests(repo):
    repo.write("tests/test_classes.py", "class TestA:\n    def test_run(self):\n        assert 1\n        assert 2\n        assert 3\n\n\nclass TestB:\n    def test_run(self):\n        assert 1\n")
    repo.commit("classes")
    repo.write("tests/test_classes.py", "class TestC:\n    def test_run(self):\n        assert 1\n        assert 2\n        assert 3\n\n\nclass TestD:\n    def test_run(self):\n        assert 1\n")
    assert _weakened(repo) == ""


def test_a_class_renamed_in_the_index_keeps_its_tests(repo):
    repo.write("tests/test_classes.py", "class TestOld:\n    def test_run(self):\n        assert 1\n")
    repo.commit("class")
    repo.write("tests/test_classes.py", "class TestNew:\n    def test_run(self):\n        assert 1\n")
    repo.git("add", "tests/test_classes.py")
    repo.write("tests/test_classes.py", "class TestNew:\n    def test_run(self):\n        assert 1\n# later\n")
    assert _weakened(repo) == ""


@pytest.mark.parametrize("line, counts", [("reader.skip_header()", False), ("raise unittest.SkipTest('no')", True), ("self.skipTest('no')", True)])
def test_a_skip_is_a_test_runners(repo, line, counts):
    repo.write("tests/test_core.py", TWO + f"\n\ndef test_c(self, reader):\n    {line}\n    assert 3\n")
    assert ("new skips" in _weakened(repo)) is counts


def test_a_renamed_yield_fixture_removes_nothing(repo):
    fixture = "import pytest\n\n\n@pytest.yield_fixture\ndef test_db():\n    yield 1\n"
    repo.write("tests/test_db.py", fixture)
    repo.commit("fixture")
    repo.write("tests/test_db.py", "import pytest\n")
    assert _weakened(repo) == ""


def test_nohup_keeps_a_hangup_from_stopping_gate(repo, tmp_path):
    os.mkfifo(tmp_path / "fifo")
    repo.git("config", "core.excludesFile", str(tmp_path / "fifo"))
    process = subprocess.Popen([sys.executable, str(OCCAM), "gate"], cwd=repo.path, env=repo.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
    try:
        time.sleep(1.5)
        process.send_signal(signal.SIGHUP)
        time.sleep(1.5)
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=60)


def test_a_claim_is_named_by_its_holder_not_called_another_agents(repo):
    """gate can't tell who runs it, so your own claim mustn't come back as another agent's."""
    assert repo.occam("coord", "claim", "app.py", "--owner", "me").returncode == 0
    repo.write("app.py", "def f():\n    return 2\n")
    out = repo.occam("gate").stdout
    assert "app.py (by me)" in out and "Other agents" not in out
