"""`occam.sh` on what a first real trial and a third review found. The two tools agree on these."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time

import pytest
from sh_support import BASHES, GIT, SOURCE, TOKEN, TOOL, make_repo

from occam_tools import query_repo
from test_occam_sh import CREDENTIALS


@pytest.fixture(params=BASHES)
def bash(request):
    return request.param


@pytest.fixture
def repo(tmp_path, bash):
    return make_repo(tmp_path / "repo", tmp_path / "state", bash)


@pytest.fixture
def plain(tmp_path, bash):
    return make_repo(tmp_path / "plain", tmp_path / "state", bash, git=False)


def _shell_value(name: str) -> str:
    """A pattern as bash would hold it."""
    body = re.search(rf"^{name}='(.*)'$", SOURCE, re.M).group(1)
    return body.replace("'\"'\"'", "'").replace("'\"$TAB\"'", "\t")


@pytest.mark.parametrize("name, pattern", [
    ("SUPPRESSIONS", query_repo.MARKERS[0][1]),
    ("SKIPPED_TESTS", query_repo.MARKERS[1][1]),
    ("FOCUSED_TESTS", query_repo.MARKERS[2][1]),
    ("ROUTES", query_repo._ROUTE),
    ("AUTOMATION", query_repo._AUTOMATION.pattern),
])
def test_the_patterns_match_occam_tools(name, pattern):
    assert _shell_value(name) == pattern


def test_a_ruby_instance_variable_isnt_a_route(repo):
    repo.write("lib/a.rb", '@cache.delete(key)\n@args.delete("version")\n')
    repo.write("web/b.py", '@app.get("/py")\ndef f():\n    return 1\n')
    repo.write("web/c.rb", "get '/rb' do\nend\n")
    output = repo.sh("entry").stdout
    assert "lib/a.rb" not in output and "web/b.py" in output and "web/c.rb" in output


def test_a_bin_folder_is_where_programs_start(repo):
    repo.write("bin/tool", "#!/bin/sh\nexit 0\n")
    assert "bin/tool" in repo.sh("entry").stdout


def test_markers_read_more_checkers_and_fewer_accidents(repo):
    repo.write("a.rb", "# converted to nanoseconds here\nx = 1 # nosec\n# rubocop:disable Style/Foo\n")
    repo.write("spec/a_spec.rb", '@src.skip(1)\nxit "x" do\nend\nskip "why"\nit.skip("y")\n')
    output = repo.sh("markers", "--top", "100").stdout
    for expected in ("a.rb:2", "a.rb:3", "spec/a_spec.rb:2", "spec/a_spec.rb:4", "spec/a_spec.rb:5"):
        assert expected in output, expected
    for accident in ("a.rb:1", "spec/a_spec.rb:1"):
        assert accident not in output, accident


def test_automation_isnt_an_owner_or_a_hotspot(repo):
    for index, author in enumerate(("dependabot[bot]", "BrewTestBot")):
        repo.write("hot.py", f"x = {index}\n")
        repo.commit("bump", author=author)
    output = repo.sh("history").stdout
    assert "dependabot" not in output and "BrewTestBot" not in output and "hot.py" not in output and "automation" in output


def test_a_repository_only_automation_touches_still_answers(tmp_path, bash):
    repo = make_repo(tmp_path / "repo", tmp_path / "state", bash, git=False)
    repo.git("init", "-q")
    repo.commit("first", author="dependabot[bot]")
    output = repo.sh("history").stdout
    assert "pyproject.toml" in output


def test_history_ranks_what_keeps_getting_fixed(repo):
    for index in range(2):
        repo.write("buggy.py", f"x = {index}\n")
        repo.commit("fix the crash")
    assert re.search(r"Most fixed.*\n\s+2 .*buggy\.py", repo.sh("history").stdout)


def test_leaks_doesnt_repeat_the_main_line_under_every_merge(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.py", "x = 1\n")
    repo.commit("side")
    repo.git("checkout", "-q", "-")
    repo.write("main.py", f'KEY = "{TOKEN}"\n')
    repo.commit("secret on the main line")
    repo.git("merge", "-q", "--no-ff", "-m", "merge", "side")
    assert repo.sh("leaks", "--top", "100").stdout.count("main.py") == 1


def test_leaks_sees_a_link_turned_into_a_file(repo):
    os.symlink("pyproject.toml", repo.path / "conf.py")
    repo.commit("a link")
    (repo.path / "conf.py").unlink()
    repo.write("conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("now a file")
    assert "conf.py" in repo.sh("leaks").stdout


def test_grafts_cant_hide_history_from_leaks(repo):
    repo.write("conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    repo.write("conf.py", "KEY = None\n")
    repo.commit("remove")
    head = repo.git("rev-parse", "HEAD").strip()
    (repo.path / ".git" / "info").mkdir(exist_ok=True)
    (repo.path / ".git" / "info" / "grafts").write_text(head + "\n")
    assert "conf.py" in repo.sh("leaks").stdout


@pytest.mark.parametrize("line", ['password = "84629175"', '{"token": "changeme", "password": "Tr0ub4dor-3xQ"}'])
def test_leaks_reads_what_the_python_version_reads(repo, line):
    repo.write("conf.py", line + "\n")
    repo.commit("add")
    assert "conf.py" in repo.sh("leaks").stdout


def test_markers_read_what_python_projects_write(repo):
    repo.write("a.py", "x = 1  # NOQA\n")
    repo.write("tests/test_a.py", "@skipUnlessDBFeature('x')\ndef test_a():\n    self.skipTest('no')\n")
    repo.write("b.py", "Entry.objects.only('id')\nmodel.fit(x)\n")
    output = repo.sh("markers", "--top", "100").stdout
    for expected in ("a.py:1", "tests/test_a.py:1", "tests/test_a.py:3"):
        assert expected in output, expected
    for accident in ("b.py:1", "b.py:2"):
        assert accident not in output, accident


def test_entry_leaves_tests_out_and_finds_how_django_starts(repo):
    repo.write("tests/pkg/__main__.py", "x = 1\n")
    repo.write("site/wsgi.py", "application = 1\n")
    repo.write("site/management/commands/migrate.py", "class Command:\n    pass\n")
    output = repo.sh("entry", "--top", "100").stdout
    assert "tests/pkg/__main__.py" not in output and "site/wsgi.py" in output and "site/management/commands/migrate.py" in output


def test_a_package_is_known_by_its_folder_not_its_init(repo):
    repo.write("lib/fields/__init__.py", "x = 1\n")
    repo.write("tests/test_a.py", "# has an __init__ method\nclass A:\n    def __init__(self):\n        pass\n")
    repo.write("tests/test_b.py", "from lib import fields\n")
    output = repo.sh("tests", "lib/fields/__init__.py").stdout
    assert "tests/test_b.py" in output and "tests/test_a.py" not in output


@pytest.mark.parametrize("line", ['DSN=postgres://u:changeme@db password=Tr0ub4dor-3xQ', 'deploy --token Xk9mQ2vLp7a --user example', 'set_token("Xk9mQ2vLp7a"); password = "changeme"',
                                  'A=postgres://u:changeme@a B=postgres://u:Xk9mQ2vLp7a@b', 'password=$PW curl -H "Authorization: Bearer Xk9mQ2vLp7a"'])
def test_a_placeholder_doesnt_hide_what_is_beside_it(repo, line):
    repo.write("conf.py", line + "\n")
    repo.commit("add")
    assert "conf.py" in repo.sh("leaks").stdout


def test_a_long_line_cant_stall_the_leak_check(repo):
    repo.write("conf.py", 'password = "changeme" ' * 45_000 + "\n")
    repo.commit("add")
    start = time.monotonic()
    assert repo.sh("leaks").returncode == 0
    assert time.monotonic() - start < 110


@pytest.mark.parametrize("line, found", [("-" * 200_000 + ' password="Xk9mQ2vLp7a"', True), ("pass" * 25_000 + "1", True), ("--" * 100_000 + " --api-key Xk9mQ2vLp7a", True),
                                         ('token: "changeme", ' * 20 + 'password: "Xk9mQ2vLp7a"', True), ('token: "changeme", ' * 60, False)])
def test_a_long_line_is_read_quickly_and_still_fully(repo, line, found):
    """BSD awk took over 200 seconds on the first of these, and the whole query timed out."""
    repo.write("conf.py", line + "\n")
    repo.commit("add")
    start = time.monotonic()
    done = repo.sh("leaks")
    assert done.returncode == 0 and ("conf.py" in done.stdout) is found
    assert time.monotonic() - start < 60


@pytest.mark.parametrize("line", [
    "token " * 60 + 'password="Xk9mQ2vLp7a"',
    "var a={token:\"$T\"};" + "Object.keys(o).forEach(function(k){});" * 55 + 'var cfg={password:"Xk9mQ2vLp7a"};',
    'password="${PW}";' + "keys;" * 52 + 'secret="Xk9mQ2vLp7a";',
    "getToken(null);" + "key;" * 60 + 'setPassword("Xk9mQ2vLp7a");',
    "pwd=$P, pass=Xk9mQ2vLp7a",
    '{pwd:{},pass:"Xk9mQ2vLp7a"}',
    "password_" + "a" * 420 + '="Xk9mQ2vLp7a";',
    "run --production-primary-database-connection-string-administrator-password Xk9mQ2vLp7a --user $USER",
    "password" + " " * 500 + '= "Xk9mQ2vLp7a"',
    "--token $T --password Xk9mQ2vLp7a",
    "{" + '"passwordToken":"$X",' * 25 + '"apiKey":"Xk9mQ2vLp7a", null}',
    "aws_secret_access_key=$A " * 26 + "aws_secret_access_key=Xk9mQ2vLp7a null",
    '"dbPasswordSecretToken":"<redacted>",' * 17 + '"apiKey":"Xk9mQ2vLp7a", null}',
    'getToken("$A");' * 50 + ' password="Xk9mQ2vLp7a"; x = null',
    "--token $T pass pass pass pass pass pass pass pass pass pass " * 5 + ' password="Xk9mQ2vLp7a" null',
    "run --" + "a" * 85 + "-password Xk9mQ2vLp7a --user null",
    "curl http://h/x--token Xk9mQ2vLp7a null",
])
def test_every_name_on_a_line_is_read(repo, line):
    """Two fresh reviews found each of these missed by earlier versions of this check, which the old one caught."""
    repo.write("conf.py", line + "\n")
    repo.commit("add")
    assert "conf.py" in repo.sh("leaks").stdout


def test_a_worktree_moved_by_hand_still_works(tmp_path, bash):
    repo = make_repo(tmp_path / "repo", tmp_path / "state", bash)
    repo.git("worktree", "add", "-q", str(tmp_path / "linked"))
    os.rename(tmp_path / "linked", tmp_path / "moved")
    assert repo.sh("size", cwd=tmp_path / "moved").returncode == 0


def test_a_planted_common_dir_cant_borrow_another_repository(tmp_path, bash):
    other = make_repo(tmp_path / "other", tmp_path / "state", bash)
    other.write("private.py", "needle_in_other = 1\n")
    other.commit("private")
    here = tmp_path / "here"
    (here / "meta" / "refs").mkdir(parents=True)
    (here / "meta" / "objects").mkdir()
    (here / ".git").write_text("gitdir: meta\n")
    (here / "meta" / "commondir").write_text(str(other.path / ".git") + "\n")
    (here / "meta" / "HEAD").write_text(other.git("rev-parse", "HEAD"))
    assert "private.py" not in other.sh("history", cwd=here).stdout


def test_a_link_cant_borrow_another_repositorys_git_folder(tmp_path, bash):
    other = make_repo(tmp_path / "other", tmp_path / "state", bash)
    other.write("private.py", "needle_in_other = 1\n")
    other.commit("private")
    here = tmp_path / "here"
    here.mkdir()
    os.symlink(other.path / ".git", here / ".git")
    done = other.sh("history", cwd=here)
    assert "private.py" not in done.stdout and done.returncode == 2


def test_a_link_cant_borrow_another_worktrees_git_file(tmp_path, bash):
    other = make_repo(tmp_path / "other", tmp_path / "state", bash)
    other.write("private.py", "needle_in_other = 1\n")
    other.commit("private")
    other.git("worktree", "add", "-q", str(tmp_path / "linked"))
    here = tmp_path / "here"
    here.mkdir()
    os.symlink(tmp_path / "linked" / ".git", here / ".git")
    done = other.sh("history", cwd=here)
    assert "private.py" not in done.stdout and done.returncode == 2


@pytest.mark.parametrize("line", ["this.skip()", "t.skip()", "it.concurrent.skip('x', f)"])
def test_every_test_runner_way_of_skipping_is_read(repo, line):
    repo.write("web/a.test.js", line + "\n")
    assert "web/a.test.js:1" in repo.sh("markers", "--top", "100").stdout


def test_a_line_cant_send_codes_to_a_terminal(repo):
    repo.write("a.py", "needle_for_terminal = '\x1b[2J'\n")
    repo.commit("add")
    output = repo.sh("grep", "needle_for_terminal").stdout
    assert "a.py" in output and "\x1b" not in output


def test_skipping_grafts_prints_nothing_on_stderr(repo):
    (repo.path / ".git" / "info").mkdir(exist_ok=True)
    (repo.path / ".git" / "info" / "grafts").write_text("")
    for question in ("leaks", "history"):
        assert repo.sh(question).stderr == "", question


def test_the_cheap_filter_lets_every_credential_through(repo):
    """It runs first, on every line of history, so a shape it misses is a secret `leaks` never sees."""
    named_as_examples = [line for line in CREDENTIALS if "aws_secret_access_key" in line]  # a value reading EXAMPLE is a placeholder to both tools, so it's no leak
    shapes = [*(line for line in CREDENTIALS if line not in named_as_examples), "AKIA" + "ABCDEFGHIJKLMNOP", "ASIA" + "ABCDEFGHIJKLMNOP", TOKEN, "github_pat_" + "a" * 22, "glpat-" + "a" * 18, "sk-" + "a" * 26, "sk-ant-" + "a" * 26, "sk_live_" + "a" * 18, "rk_live_" + "a" * 18,
              "xoxb-" + "1" * 14, "xoxs-" + "1" * 14, "npm_" + "a" * 32, "hf_" + "a" * 32, "pypi-" + "a" * 32, "-----BEGIN RSA " + "PRIVATE KEY-----", "AIza" + "a" * 35, "eyJ" + "a" * 22 + ".eyJ" + "a" * 22 + ".sig",
              "A" * 44, 'os.getenv("API_KEY", "Xk9mQ2vLp7a")', "export DB_PWD=Xk9mQ2vLp7a", "--api-key Xk9mQ2vLp7a", "https://user:Xk9mQ2vLp7a@example.invalid/", "Basic dXNlcjpwYXNzd29yZA1"]
    for index, line in enumerate(shapes):
        repo.write(f"shapes/s{index}.py", line + "\n")
    repo.commit("shapes")
    output = repo.sh("leaks", "--top", "1000").stdout
    missed = [shapes[index] for index in range(len(shapes)) if f"shapes/s{index}.py\n" not in output]
    assert not missed


def test_a_nested_repository_cant_name_its_parent_as_its_files(tmp_path, bash):
    outer = make_repo(tmp_path / "outer", tmp_path / "state", bash)
    outer.write("private.py", "needle_in_parent = 1\n")
    outer.commit("private")
    inner = outer.path / "inner"
    inner.mkdir()
    subprocess.run([GIT, "init", "-q"], cwd=inner, check=True)
    subprocess.run([GIT, "config", "core.worktree", "../.."], cwd=inner / ".git", check=True)
    done = outer.sh("grep", "needle_in_parent", cwd=inner)
    assert "private.py" not in done.stdout and done.returncode == 2


def test_a_git_file_cant_borrow_another_repository(tmp_path, bash):
    other = make_repo(tmp_path / "other", tmp_path / "state", bash)
    other.write("private.py", "needle_in_other = 1\n")
    other.commit("private")
    here = tmp_path / "here"
    here.mkdir()
    (here / ".git").write_text(f"gitdir: {other.path / '.git'}\n")
    done = other.sh("history", cwd=here)
    assert "private.py" not in done.stdout and done.returncode == 2


def test_a_linked_worktree_and_a_submodule_are_still_fine(tmp_path, bash):
    repo = make_repo(tmp_path / "repo", tmp_path / "state", bash)
    repo.git("worktree", "add", "-q", str(tmp_path / "linked"))
    assert repo.sh("size", cwd=tmp_path / "linked").returncode == 0
    library = tmp_path / "library"
    library.mkdir()
    for args in (("init", "-q"), ("-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-q", "--allow-empty", "-m", "c")):
        subprocess.run([GIT, *args], cwd=library, check=True)
    repo.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "vendored_library")
    assert repo.sh("size", cwd=repo.path / "vendored_library").returncode == 0


def test_a_folder_name_with_a_line_break_cant_read_outside(tmp_path, plain):
    (tmp_path / "outside_secret.py").write_text("needle_outside = 1\n")
    (plain.path / "a\n..").mkdir()
    (plain.path / "a\n.." / "outside_secret.py").write_text("x = 1\n")
    assert "needle_outside" not in plain.sh("grep", "needle_outside").stdout


def test_a_config_it_cant_read_doesnt_break_it(repo):
    repo.write(".occam.json", '{"ignore": []}')
    (repo.path / ".occam.json").chmod(0)
    try:
        assert repo.sh("grep", "total").returncode == 0
    finally:
        (repo.path / ".occam.json").chmod(0o644)


def test_a_huge_config_doesnt_break_it(repo):
    repo.write(".occam.json", '{"ignore": ["' + "x" * 3_000_000 + '"]}')
    assert repo.sh("grep", "total").returncode in (0, 1)


def _tree(root: int) -> set[int]:
    rows = [row.split()[:2] for row in subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, errors="replace").stdout.split("\n") if len(row.split()) >= 2]
    found = {root}
    while True:
        more = {int(pid) for pid, parent in rows if pid.isdecimal() and parent.isdecimal() and int(parent) in found} - found
        if not more:
            return found
        found |= more


def _alive(pids: set[int]) -> set[int]:
    left = set()
    for pid in pids:
        try:
            os.kill(pid, 0)
            left.add(pid)
        except ProcessLookupError:
            pass
    return left


def _blocked(repo, tmp_path, seconds: str) -> subprocess.Popen:
    os.mkfifo(tmp_path / "fifo")
    repo.git("config", "core.excludesFile", str(tmp_path / "fifo"))
    return subprocess.Popen([repo.bash, str(TOOL), "size"], cwd=repo.path, env={**repo.env, "OCCAM_TIMEOUT": seconds}, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)


@pytest.mark.parametrize("name", ["ALRM", "USR2", "XCPU"])
def test_other_signals_stop_everything_too(repo, tmp_path, name):
    process = _blocked(repo, tmp_path, "60")
    started: set[int] = set()
    try:
        time.sleep(1.5)
        started = _tree(process.pid)
        process.send_signal(getattr(signal, f"SIG{name}"))
        process.communicate(timeout=120)
        deadline = time.monotonic() + 30
        while _alive(started - {process.pid}) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(started - {process.pid})
    finally:
        for pid in _alive(started - {process.pid}):
            os.kill(pid, signal.SIGKILL)
        process.kill()
        process.wait()


def test_the_timer_stops_the_work_even_if_the_script_is_killed(repo, tmp_path):
    process = _blocked(repo, tmp_path, "3")
    started: set[int] = set()
    try:
        time.sleep(1)
        started = _tree(process.pid)
        process.kill()
        process.wait()
        deadline = time.monotonic() + 60
        while _alive(started - {process.pid}) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _alive(started - {process.pid})
    finally:
        for pid in _alive(started - {process.pid}):
            os.kill(pid, signal.SIGKILL)
