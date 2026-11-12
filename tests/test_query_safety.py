"""`occam query` against repositories that try to mislead it: credentials, settings, hostile files, scale."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from query_support import API, CORE, GIT, OCCAM, TOKEN, Repo, make_repo, python_repo

from occam_tools import files as filesystem, query, query_code, toolrun


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo", tmp_path / "state")


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """A repository no test changes, so the read-only queries needn't each build one."""
    base = tmp_path_factory.mktemp("shared")
    return make_repo(base / "repo", base / "state")


# ---------------------------------------------------------------- credentials, in every form and every query

CREDENTIALS = ['password = "sunshine"', 'db_password = "mysecretprod1"', 'password: str = "Xk9mQ2vLp7"', 'os.getenv("API_KEY", "Xk9mQ2vLp7aa")', "API_KEY=Xk9mQ2vLp7bb",
               "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", 'PASSWORD = "correct horse battery"', 'url = "postgres://admin:p%40ss%21word@db/x"',
               "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7", 'key = "AKIAIOSFODNN7EXAMPLE"\t# a tab before this',
               'DB_PASS = "hunter2xyz"', 'pass: "hunter2xyz"', "password=Tr0ub4dor$3", 'password = b"hunter2xyz"', "PASSWORD=correcthorsebatterystaple", "redis://:s3cr3tpw@cache.internal:6379/0",
               "https://ghtoken123abc@github.com/x", "Authorization: Bearer abc123def456ghi", "--password hunter2xyz", "sk_live_abcdefghijklmnop1234", "glpat-abcdefghijklmnop1234",
               "github_pat_abcdefghijklmnop123456", "ASIAABCDEFGHIJKLMNOP", 'set_password("hunter2xyz")', "export DB_PASSWORD=HUNTERPASSWORD", 'CMD ["run", "--password=Xk9mQ2vLp7"]',
               "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\r", 'if password == "hunter2xyz":']
SECRET_PIECES = ["sunshine", "mysecretprod1", "Xk9mQ2vLp7", "wJalr", "correct horse", "p%40ss", "MIIEvQ", "AKIAIOSFODNN7EXAMPLE"]


@pytest.mark.parametrize("line", CREDENTIALS, ids=lambda line: line[:18])
def test_each_credential_shape_is_withheld(line):
    assert "withheld" in query.safe_line(line)


@pytest.mark.parametrize("line", ["token = new_token", "password = get_password()", "token: str", "secret_name = request.args", "def check(password):", "x = 'http://localhost:8080/x'", "if password == other:", "api_key = config.api_key",
                                  "max_tokens = 1024", "def login(token: Token, user: User)", "api_key=settings.API_KEY,", "accessToken: accessToken,", "tokenizer: AutoTokenizer,", "token_url: https://example.com/oauth/token",
                                  "self._token = None", "pwd = None", "page_token=None,", "token_count = 0", "password_min_length = 8", "secret_length: 32", 'passenger = "bob"', "if token==END:", "token=TOKEN)", "ssh://git@github.com/x"])
def test_ordinary_code_stays_readable(line):
    assert query.safe_line(line) == line


def test_placeholders_are_withheld_from_output_but_arent_reported_as_leaks():
    for line in ('password = "changeme"', 'password = "test"', 'password = "${DB_PASS}"', 'password = "your-password"', 'password = "<password>"', 'api_key = "some_setting_name"', "postgres://user:password@db/x"):
        found = query.credential_in(line)
        assert found and not query.worth_reporting(found), line
    for line in ('password = "Xk9mQ2vLp7"', TOKEN, 'PASSWORD = "Pa$$w0rd!2024"', 'API_KEY = "9f8a7TeSt3b2c1d0e9f8a7b6c5"', 'db_password = "Latest!2024q"', 'password = "kj3{h4}5kj"'):
        assert query.worth_reporting(query.credential_in(line)), line


@pytest.mark.parametrize("args", [("grep", "PASSWORD|password"), ("find", "PASSWORD"), ("commands", "--top", "100"), ("entry", "--top", "100"), ("outline", "app/sec.py"), ("api", "app/sec.py")], ids=lambda args: args[0])
def test_no_query_prints_a_credential(repo, args):
    repo.write("app/sec.py", 'PASSWORD = "sunshine"\ndef login(user, password="Xk9mQ2vLp7"):\n    """Uses password = "Xk9mQ2vLp7" by default."""\n    return 1\n')
    repo.write("Makefile", 'deploy:\n\tPASSWORD="Xk9mQ2vLp7" run\n')
    repo.write("package.json", '{"name": "x", "bin": {"x": "API_KEY=Xk9mQ2vLp7bb"}, "scripts": {"s": "PASSWORD=Xk9mQ2vLp7 go"}}')
    repo.write("web/routes.py", '@app.get("/x?password=Xk9mQ2vLp7")\ndef f():\n    pass\n')
    for form in ((), ("--format", "json")):
        output = repo.occam("query", *args, *form).stdout
        assert "sunshine" not in output and "Xk9mQ2vLp7" not in output, output[:400]

# ---------------------------------------------------------------- settings a repository can use to make a failure look clean

@pytest.mark.parametrize("key, value", [("color.ui", "always"), ("color.grep", "always"), ("grep.column", "true"), ("grep.fullName", "true"), ("grep.lineNumber", "false"), ("grep.fallbackToNoIndex", "true")])
def test_grep_settings_cant_change_an_answer(repo, key, value):
    before = repo.query("find", "total")["total"]
    routes_before = repo.query("entry", "--top", "50")["totals"]
    repo.git("config", key, value)
    assert repo.query("find", "total")["total"] == before > 0
    assert repo.query("entry", "--top", "50")["totals"] == routes_before
    assert "tests/test_tool.py" in repo.query("impact", "tool.py", "--top", "50")["tests"]


@pytest.mark.parametrize("attributes", ["* -diff\n", "* binary\n", "* -text\n"])
def test_attributes_cant_hide_a_match_or_a_leak(repo, attributes):
    repo.write(".gitattributes", attributes)
    repo.write("app/conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    assert repo.query("find", "total")["total"] > 0
    assert "app/conf.py" in [row["path"] for row in repo.query("leaks")["rows"]]


def test_a_real_binary_stays_out_of_search(repo):
    (repo.path / "blob.dat").write_bytes(b"total\0total\n")
    assert query.search(repo.path, "total", [str(repo.path / "blob.dat")])[0] == []


@pytest.mark.parametrize("key, value", [("core.bigFileThreshold", "1"), ("log.showRoot", "false"), ("i18n.logOutputEncoding", "UTF-16"), ("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"), ("color.diff", "always"), ("color.ui", "always"), ("diff.relative", "true")])
def test_settings_cant_hide_history_or_leaks(tmp_path, key, value):
    repo = make_repo(tmp_path / "r", tmp_path / "s")
    repo.write("app/conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    repo.git("config", key, value)
    assert "app/conf.py" in [row["path"] for row in repo.query("leaks")["rows"]]
    assert repo.query("history")["commits_read"] == 2


def test_leaks_reads_what_could_hide_from_it(repo):
    repo.write("a.py", f'KEY = "{TOKEN}"\n++ b/tests/x.py\nOTHER = "{TOKEN}"\n')
    repo.write('ev"il.py', f'KEY = "{TOKEN}"\n')
    repo.write("old.py", "x = 1\n" * 20)
    repo.commit("add")
    repo.git("mv", "old.py", "new.py")
    repo.write("new.py", "x = 1\n" * 20 + f'KEY = "{TOKEN}"\n')
    repo.commit("rename with an edit")
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.py", f'KEY = "{TOKEN}"\n')
    repo.commit("on a branch")
    repo.git("checkout", "-q", "-")
    rows = repo.query("leaks", "--top", "100")["rows"]
    assert {"a.py", 'ev"il.py', "new.py", "side.py"} <= {row["path"] for row in rows}
    assert [row["lines"] for row in rows if row["path"] == "a.py"] == [2]


def test_leaks_cant_be_hidden_by_merge_settings_or_replaced_commits(repo):
    repo.write("a.py", f'KEY = "{TOKEN}"\n')
    repo.commit("a commit that gets hidden")
    repo.write("b.py", "x = 1\n")
    repo.commit("next")
    repo.git("config", "log.diffMerges", "off")
    repo.git("replace", "--graft", "HEAD", "HEAD~2")
    assert "a.py" in [row["path"] for row in repo.query("leaks")["rows"]]


def test_leaks_says_a_shallow_clone_is_cut_short(repo, tmp_path):
    repo.write("x.py", "x = 1\n")
    repo.commit("more")
    clone = tmp_path / "clone"
    subprocess.run([GIT, "clone", "-q", "--depth", "1", f"file://{repo.path}", str(clone)], check=True, env=repo.env)
    assert "shallow clone" in Repo(clone, tmp_path / "s3").text("leaks")


def test_leaks_reads_a_secret_added_in_a_merge(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.py", "x = 1\n")
    repo.commit("side")
    repo.git("checkout", "-q", "-")
    repo.git("merge", "-q", "--no-ff", "--no-commit", "side")
    repo.write("merged.py", f'KEY = "{TOKEN}"\n')
    repo.commit("merge")
    assert "merged.py" in [row["path"] for row in repo.query("leaks")["rows"]]


def test_a_query_never_writes_to_git_even_when_a_file_looks_changed(repo):
    (repo.path / "app/core.py").write_text(CORE)  # same content, newer time: what makes git want to refresh its index
    os.utime(repo.path / "app/core.py", (2_000_000_000, 2_000_000_000))
    index = repo.path / ".git" / "index"
    before = (index.stat().st_mtime_ns, index.read_bytes())
    for args in (("impact", "--changed"), ("api", "--base", "HEAD"), ("size",), ("find", "total"), ("history",)):
        assert repo.occam("query", *args).returncode == 0
    assert repo.occam("scan", "--changed", "--isolated").returncode == 0
    assert (index.stat().st_mtime_ns, index.read_bytes()) == before


def test_old_git_cant_be_made_to_run_what_a_repository_names(repo, tmp_path):
    """Before 2.31 git ignores GIT_CONFIG_COUNT, so a driver stays on. The shim plays that part by dropping it, and only that part."""
    marker = tmp_path / "ran"
    payload = tmp_path / "payload.sh"
    payload.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    payload.chmod(0o755)
    repo.git("config", "filter.x.clean", str(payload))
    repo.write(".gitattributes", "* filter=x\n")
    os.utime(repo.path / "app/core.py", (2_000_000_000, 2_000_000_000))
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "git").write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version 2.30.1"; exit 0; fi\nunset GIT_CONFIG_COUNT\nexec {GIT} "$@"\n')
    (shim / "git").chmod(0o755)
    env = {**repo.env, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}
    for args in (("impact", "--changed"), ("api", "--base", "HEAD"), ("history",), ("find", "total")):
        subprocess.run([sys.executable, str(OCCAM), "query", *args], cwd=repo.path, env=env, capture_output=True, text=True, timeout=60)
    assert not marker.exists()


def test_a_working_tree_in_a_parent_is_refused(tmp_path):
    home = tmp_path / "home"
    (home / "dl").mkdir(parents=True)
    repo = make_repo(home / "dl" / "evil", tmp_path / "s")
    (home / "notes.txt").write_text("SECRETMARK\n")
    repo.git("config", "core.worktree", str(home))
    done = repo.occam("query", "grep", "SECRETMARK")
    assert done.returncode == 2 and "notes.txt" not in done.stdout


def test_setups_that_are_fine_stay_fine(repo, tmp_path):
    linked = tmp_path / "linked"
    repo.git("worktree", "add", "-q", str(linked))
    assert Repo(linked, tmp_path / "s4").occam("query", "size").returncode == 0
    (tmp_path / "ln").symlink_to(repo.path)
    assert repo.occam("query", "size", cwd=tmp_path / "ln").returncode == 0
    other_git = tmp_path / "sep"
    subprocess.run([GIT, "init", "-q", f"--separate-git-dir={tmp_path / 'sep.git'}", str(other_git)], check=True, env=repo.env)
    (other_git / "a.py").write_text("x = 1\n")
    assert Repo(other_git, tmp_path / "s5").occam("query", "size").returncode == 0
    trailing = tmp_path / "name with a trailing space "
    trailing.mkdir()
    subprocess.run([GIT, "init", "-q", str(trailing)], check=True, env=repo.env)
    assert Repo(trailing, tmp_path / "s6").occam("query", "size").returncode == 0


def test_a_stat_only_change_isnt_reported_as_differing_from_what_is_staged(repo):
    os.utime(repo.path / "app/core.py", (2_000_000_000, 2_000_000_000))
    repo.write("app/api.py", API + "\n# staged\n")
    repo.git("add", "app/api.py")
    os.utime(repo.path / "app/api.py", (2_000_000_000, 2_000_000_000))
    assert filesystem.staged_differently(repo.path) == []
    repo.write("app/api.py", API + "\n# staged, then edited\n")
    assert filesystem.staged_differently(repo.path) == ["app/api.py"]


def test_a_staged_secret_gone_from_disk_still_stops_gate(repo):
    """A patch has no +++ line for a deleted file, so reading names from the patch alone let this through with `No changes to gate`."""
    repo.write("conf.py", f'KEY = "{TOKEN}"\n')
    repo.git("add", "conf.py")
    (repo.path / "conf.py").unlink()
    assert filesystem.staged_differently(repo.path) == ["conf.py"]
    done = repo.occam("gate")
    assert done.returncode == 1 and "hardcoded-secret" in done.stdout


def test_a_working_tree_elsewhere_is_refused(repo, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "other.py").write_text("total = 1\n")
    repo.git("config", "core.worktree", str(elsewhere))
    done = repo.occam("query", "grep", "total")
    assert done.returncode == 2 and "other.py" not in done.stdout and "Nothing was checked" in done.stdout


def test_a_config_that_hides_everything_says_so(repo):
    repo.write(".occam.json", '{"ignore": ["*"]}')
    output = repo.text("grep", "total")
    assert "0 matching" in output and "leaves out: *" in output
    assert repo.query("size")["config_ignores"] == ["*"]


def test_the_ignore_note_appears_once_on_an_empty_answer(repo):
    repo.write(".occam.json", '{"ignore": ["app"]}')
    for question in ("grep", "find"):
        output = repo.text(question, "nothing_is_called_this")
        assert output.count("leaves out") == 1, output


def test_leaks_doesnt_claim_a_setting_left_out_what_it_read(repo):
    repo.write(".occam.json", '{"ignore": ["secrets"]}')
    repo.write("secrets/conf.py", f'KEY = "{TOKEN}"\n')
    repo.write("secrets/other.py", f'KEY = "{TOKEN}"\n')
    repo.commit("one commit, two files")
    output = repo.text("leaks")
    assert "secrets/conf.py" in output and "leaves out" not in output and "credential-shaped lines: 2, in 2 files" in output
    assert repo.query("leaks")["config_ignores"] == []


def test_an_empty_answer_says_what_it_cant_speak_for(shared):
    assert "unless you name one" in shared.text("find", "nothing_at_all_here")
    assert "unless you name one" in shared.text("grep", "nothing_at_all_here")


def test_naming_an_ignored_file_searches_it(repo):
    repo.write("ignored.py", "needle = 1\n")
    repo.write(".gitignore", "ignored.py\n")
    assert repo.query("find", "needle")["total"] == 0
    assert repo.query("find", "needle", "ignored.py")["total"] == 1


def test_a_newline_in_a_file_name_doesnt_lose_it(repo):
    repo.write("odd\nname.py", "needle = 1\n")
    assert repo.query("find", "needle")["total"] == 1


def test_grep_says_what_was_too_large_to_read(repo):
    repo.write("huge.py", "needle = 1\n" * 200_000)
    data = repo.query("grep", "needle")
    assert data["too_large"] == 1 and "weren't searched" in repo.text("grep", "needle")


def test_a_hit_in_a_file_too_large_to_load_still_counts(repo):
    repo.write("huge.py", "x = f()  # noqa\n" * 200_000)
    assert "huge.py" in [path for path, _ in repo.query("markers")["kinds"]["suppression"]["top_files"]]


def test_a_search_that_stopped_says_so(repo, monkeypatch):
    from occam_tools import query_code, query_repo
    assert "stopped at its limit" in query_repo.render_markers({"kinds": {}, "stopped_at_limit": True})
    assert "stopped at its limit" in query_repo.render_entry({"totals": {}, "kinds": {}, "stopped_at_limit": True})
    assert "stopped at its limit" in query_code.render_boundaries({"kinds": {"money": 1}, "kind": "money", "stopped_at_limit": True, "sites": {"money": []}, "files_total": 1, "files": []})


def test_other_files_hits_cant_use_up_the_limit_for_tests(repo, monkeypatch):
    repo.write("docs/a.txt", "tool.py\n" * 300)
    monkeypatch.setattr(query, "MAX_HITS", 100)
    hits, stopped = query.search(repo.path, "tool.py", fixed=True, limit=100, only=lambda path: path.startswith("tests/"))
    assert not stopped and [hit.path for hit in hits] == ["tests/test_tool.py"]

# ---------------------------------------------------------------- what a hostile file can't do

@pytest.mark.parametrize("name, content, args", [
    ("tsconfig.json", '{"compilerOptions": "x"}', ("graph",)),
    ("tsconfig.json", '{"compilerOptions": {"paths": 3}}', ("impact", "tool.py")),
    ("coverage.xml", '<class name="x" filename="a.py" line-rate="1.2.3"></class>', ("tests",)),
    ("package.json", '{"name": ["a"], "bin": "x.js"}', ("entry",)),
    ("package.json", '{"name": {"a": 1}, "main": 3}', ("entry",)),
])
def test_a_malformed_file_gets_an_answer_not_a_traceback(repo, name, content, args):
    repo.write(name, content)
    done = repo.occam("query", *args)
    assert done.returncode == 0 and "Traceback" not in done.stderr


def test_deep_nesting_gets_an_answer_not_a_traceback(repo):
    repo.write("deep.py", "x = " + "(" * 5000 + ")" * 5000 + "\ntotal = 1\n")
    for args in (("find", "total"), ("outline", "deep.py")):
        done = repo.occam("query", *args)
        assert done.returncode == 0 and "Traceback" not in done.stderr


def test_a_path_outside_the_root_is_an_error_for_graph_too(shared, tmp_path):
    done = shared.occam("query", "graph", str(tmp_path), "--root", str(shared.path))
    assert done.returncode == 2 and "outside this project" in done.stdout


def test_a_fifo_gitignore_cant_hang_a_folder(tmp_path):
    repo = make_repo(tmp_path / "r", tmp_path / "s", git=False)
    (repo.path / ".gitignore").unlink()
    os.mkfifo(repo.path / ".gitignore")
    assert repo.occam("query", "size").returncode == 0


@pytest.mark.parametrize("args", [("graph",), ("impact", "m1.py"), ("tests",)], ids=lambda args: args[0])
def test_the_timeout_holds_while_a_first_scan_is_reading(tmp_path, args):
    """A worker pool used to catch the alarm as an OSError and read everything again with no limit left."""
    repo = python_repo(tmp_path, {f"m{index}.py": "def f(a, b):\n    return [x for x in a if x and b]\n" * 120 for index in range(1500)})
    started = time.time()
    done = repo.occam("query", *args, "--timeout", "1")
    assert done.returncode == 2 and "Nothing was checked" in done.stdout and time.time() - started < 40


def test_a_query_that_runs_too_long_stops_with_exit_2(repo):
    done = repo.occam("query", "grep", "(a+)+$", "--timeout", "1")
    assert done.returncode in (0, 2)  # finishing in time is fine. What matters is that this returns at all
    repo.write("slow.py", "a" * 40 + "!\n")
    done = repo.occam("query", "grep", "(a+)+$", "slow.py", "--timeout", "1")
    assert done.returncode == 2 and "Nothing was checked" in done.stdout


def test_an_unexpected_failure_is_exit_2_not_a_clean_answer(repo, monkeypatch, capsys):
    from occam_tools import cli, query_repo
    monkeypatch.setattr(query_repo, "size", lambda *args: 1 / 0)
    monkeypatch.chdir(repo.path)
    assert cli.main(["query", "size"]) == 2
    assert "Nothing was checked" in capsys.readouterr().out


def test_outline_is_bounded_across_files_and_in_json(repo):
    for index in range(12):
        repo.write(f"many/m{index}.py", "".join(f"def f{i}():\n    pass\n" for i in range(5)))
    data = repo.query("outline", "many", "--top", "7")
    assert sum(len(row["symbols"]) for row in data["files"]) == 7
    assert sum(row["symbols_total"] for row in data["files"]) == 60


def test_a_route_label_is_bounded(repo):
    repo.write("web/long.py", '@app.get("/' + "x" * 5000 + '")\ndef f():\n    pass\n')
    assert len(max(repo.text("entry", "--top", "100").split("\n"), key=len)) < 400


def test_each_tool_is_catalogued_once():
    names = [tool.name for tool in toolrun.CATALOG]
    assert len(names) == len(set(names))


def test_scan_isolated_with_changes_reads_only_the_changes(repo):
    repo.write("a/a.py", "x = 1\n")
    repo.write("b/b.py", "y = 1\n")
    repo.commit()
    repo.write("a/a.py", "x = 2\n")
    data = json.loads(repo.occam("scan", "--isolated", "--changed", "--format", "json").stdout)
    assert data["stats"]["files"] == 1 and data["stats"]["lines"] < 5

# ---------------------------------------------------------------- text is the default, so it has to say the same thing

@pytest.mark.parametrize("args, expected", [
    (("size",), ("lines in", "By directory", "Largest files", "app/core.py")),
    (("commands",), ("Listed, not run", "pytest -q")),
    (("entry",), ("Program starts", "Installed commands", "HTTP routes", "GET /health", "Container")),
    (("markers",), ("suppression:", "skipped-test:", "focused-test:", "hidden-check:")),
    (("history",), ("commits from", "Authors:", "Most changed files", "app/core.py")),
    (("history", "app/core.py"), ("Recent commits", "init")),
    (("leaks",), ("Read the diffs of 1 commits",)),
    (("outline", "app/core.py"), ("5-9", "function total(a, b=1, *, cap=None)", "class Ledger", "# Add.")),
    (("find", "total"), ("Defined (1)", "Imported", "Called", "in post", "In strings", "In comments")),
    (("grep", "Ledger"), ("matching lines", "app/core.py:12", "[code]")),
    (("functions", "--top", "3"), ("functions.", "complexity", "Sorted by lines")),
    (("api", "app/core.py"), ("3 public names", "function total(", "class Ledger", "By convention")),
    (("boundaries",), ("An inventory, not findings", "Read these first", "app/payments.py", "money")),
    (("boundaries", "--kind", "money"), ("money:", "app/payments.py:5")),
    (("graph",), ("import edges", "Most depended on", "Import cycles: 0", "Between top-level folders")),
    (("graph", "app/core.py"), ("Imported by:", "app/api.py", "Outside this repository", "Read from text and syntax")),
    (("impact", "app/core.py"), ("Tests to run", "tests/test_core.py", "Direct dependents", "Read from text and syntax")),
    (("tests",), ("test files", "No test reaches these", "app/lonely.py", "No coverage report")),
    (("tests", "app/core.py"), ("reach app/core.py", "tests/test_core.py")),
], ids=lambda value: " ".join(value) if isinstance(value, tuple) and value and value[0][:1].islower() and len(value) <= 3 and value[0] in ("size", "commands", "entry", "markers", "history", "leaks", "outline", "find", "grep", "functions", "api", "boundaries", "graph", "impact", "tests") else "")
def test_text_output_says_what_the_data_says(shared, args, expected):
    output = shared.text(*args)
    for piece in expected:
        assert piece in output, f"{piece!r} missing from: {output[:600]}"


def test_api_text_shows_a_breaking_change(repo):
    repo.write("app/mod.py", "def f(a):\n    pass\n\n\ndef gone():\n    pass\n")
    repo.commit()
    repo.write("app/mod.py", "def f(renamed):\n    pass\n\n\ndef new():\n    pass\n")
    output = repo.text("api", "--base", "HEAD")
    for piece in ("1 names removed", "1 changed in a way that can break", "0 changed otherwise", "1 added", "Removed", "function gone", "parameter removed or renamed: a", "was (a)", "now (renamed)", "Added", "function new"):
        assert piece in output, piece

# ---------------------------------------------------------------- safety and scale

ALL_QUERIES = (("size",), ("commands",), ("entry",), ("markers",), ("history",), ("leaks",), ("outline", "app/core.py"), ("find", "total"), ("grep", "total"), ("functions",),
               ("api",), ("boundaries",), ("graph",), ("graph", "app/core.py"), ("impact", "app/core.py"), ("impact", "--changed"), ("tests",), ("tests", "app/core.py"))


def _hostile(repo: Repo, marker: Path) -> None:
    payload = repo.path / ".git" / "payload.sh"
    payload.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    payload.chmod(0o755)
    for key, value in (("core.fsmonitor", payload), ("core.pager", payload), ("core.sshCommand", payload), ("diff.external", payload), ("filter.x.clean", payload),
                       ("filter.x.smudge", payload), ("diff.x.textconv", payload), ("gpg.program", payload), ("core.hooksPath", payload.parent)):
        repo.git("config", key, str(value))
    repo.write(".gitattributes", "* filter=x diff=x\n")
    (repo.path / ".git" / "post-index-change").write_text(f"#!/bin/sh\ntouch {marker}\n")


@pytest.mark.parametrize("args", ALL_QUERIES, ids=lambda args: " ".join(args))
def test_no_query_runs_what_a_hostile_repository_names(tmp_path, args):
    repo = make_repo(tmp_path / "r", tmp_path / "s")
    marker = tmp_path / "ran"
    repo.write("conftest.py", f"open({str(marker)!r}, 'w')\n")
    repo.write("app/core.py", CORE + f"\nopen({str(marker)!r}, 'w')\n")
    _hostile(repo, marker)
    assert repo.occam("query", *args).returncode == 0
    assert not marker.exists(), f"{args} ran something"


@pytest.mark.parametrize("args", ALL_QUERIES, ids=lambda args: " ".join(args))
def test_no_query_writes_to_the_repository(shared, args):
    before = sorted((str(p), p.stat().st_mtime_ns) for p in shared.path.rglob("*") if ".git" not in p.parts)
    assert shared.occam("query", *args).returncode == 0
    assert before == sorted((str(p), p.stat().st_mtime_ns) for p in shared.path.rglob("*") if ".git" not in p.parts)


@pytest.mark.parametrize("args", [a for a in ALL_QUERIES if a[0] not in ("history", "leaks") and "--changed" not in a], ids=lambda args: " ".join(args))
def test_every_query_works_on_a_folder_that_isnt_a_repository(tmp_path, args):
    repo = make_repo(tmp_path / "r", tmp_path / "s", git=False)
    assert repo.occam("query", *args).returncode == 0


@pytest.mark.parametrize("args", [("find", "total"), ("boundaries",), ("markers",), ("entry",)], ids=lambda args: args[0])
def test_a_folder_and_a_repository_give_the_same_answer(tmp_path, args):
    """git grep and the walk that stands in for it read the same expressions on different engines."""
    with_git = make_repo(tmp_path / "a", tmp_path / "s1")
    without = make_repo(tmp_path / "b", tmp_path / "s2", git=False)
    assert with_git.query(*args, "--top", "1000") == without.query(*args, "--top", "1000")


def test_queries_run_from_a_subfolder(shared):
    assert shared.query("find", "total", cwd=shared.path / "app")["total"] == shared.query("find", "total")["total"]
    assert shared.query("size", ".", cwd=shared.path / "app")["files"] == shared.query("size", "app")["files"]


def test_query_help_lists_every_query(shared):
    done = shared.occam("query", "--help")
    for name in ("size", "commands", "entry", "markers", "history", "leaks", "outline", "find", "grep", "functions", "api", "boundaries", "graph", "impact", "tests"):
        assert name in done.stdout


def test_stream_git_raises_rather_than_end_early_and_look_complete(tmp_path):
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.write("a", "x\n")
    repo.git("init", "-q")
    with pytest.raises(filesystem.GitProblem):
        list(filesystem.stream_git(repo.path, "log", "--not-a-real-flag"))
    assert list(filesystem.stream_git(repo.path, "grep", "-e", "nothing-here", ok_codes=(0, 1))) == []


def test_a_slow_git_gets_stopped(tmp_path, monkeypatch):
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.git("init", "-q")
    fake = tmp_path / "bin"
    fake.mkdir()
    real = shutil.which("git")
    (fake / "git").write_text(f'#!/bin/sh\ncase "$*" in *config*) exec {real} "$@" ;; esac\nsleep 30\n')
    (fake / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    filesystem._driver_overrides.clear()
    with pytest.raises(filesystem.GitProblem):
        list(filesystem.stream_git(repo.path, "log", timeout=1))


def test_search_stops_at_its_limit_and_says_so(shared):
    hits, stopped = query.search(shared.path, "def", limit=2)
    assert len(hits) == 2 and stopped
    hits, stopped = query.search(shared.path, "def", limit=10_000)
    assert not stopped


def test_search_takes_several_fixed_strings_on_both_engines(tmp_path):
    with_git = make_repo(tmp_path / "a", tmp_path / "s1")
    without = make_repo(tmp_path / "b", tmp_path / "s2", git=False)
    for repo in (with_git, without):
        hits, _ = query.search(repo.path, ["tool.py", "lib.sh"], fixed=True)
        assert {hit.path for hit in hits} >= {"tests/test_tool.py", "scripts/run.sh"}
    assert query.search(with_git.path, ["tool.py", "lib.sh"], fixed=True)[0] == query.search(without.path, ["tool.py", "lib.sh"], fixed=True)[0]


def test_views_keep_only_recent_files_and_still_answer_for_the_rest(repo, monkeypatch):
    monkeypatch.setattr(query, "MAX_FILES_KEPT", 2)
    views = query.Views(repo.path)
    for path in ("app/core.py", "app/api.py", "tool.py"):
        views.source(path)
    assert len(views._sources) == len(views._comment_lines) == 2
    assert views.kind_at("app/api.py", 14, 2) == "comment"
    assert views.kind_at("app/core.py", 2, 0) == "code"


def test_a_file_with_no_strings_or_comments_still_counts_as_code(repo):
    repo.write("plain.py", "x = 1\n")
    assert query.Views(repo.path).kind_at("plain.py", 1, 0) == "code"


def test_light_records_dont_reach_the_cache(repo):
    """The queries read records without what scan's rules need. A scan after one must still find everything."""
    repo.write("app/bad.py", "import requests\nrequests.get('http://x.invalid')\n")
    expected = json.loads(repo.occam("scan", "--no-cache", "--format", "json").stdout)["findings"]
    repo.query("graph")
    assert json.loads(repo.occam("scan", "--format", "json").stdout)["findings"] == expected
    repo.query("functions")
    assert json.loads(repo.occam("scan", "--format", "json").stdout)["findings"] == expected


def test_position_kinds(shared):
    views = query.Views(shared.path)
    assert views.kind_at("app/api.py", 14, 2) == "comment"
    assert views.kind_at("app/api.py", 15, 10) == "string"
    assert views.kind_at("app/api.py", 1, 0) == "code"
    assert views.kind_at("README.md", 1, 0) == "text"


def test_a_credential_shaped_line_is_withheld():
    assert "withheld" in query.safe_line(f'x = "{TOKEN}"')
    assert query.safe_line("  plain line  ") == "plain line"
    assert query.safe_line("y " * 250).endswith("...")

# ---------------------------------------------------------------- what giant repositories need elsewhere

def test_scan_isolated_reads_only_what_it_was_given(repo):
    repo.write("elsewhere/bad.py", "from nowhere_at_all import x\n")
    repo.write("only/a.py", "import requests\nrequests.get('http://x.invalid')\n")
    done = repo.occam("scan", "only", "--isolated", "--format", "json")
    data = json.loads(done.stdout)
    assert data["stats"]["isolated"] is True and data["stats"]["files"] == 1
    assert "missing-timeout" in [row["rule"] for row in data["findings"]]
    assert "phantom-import" not in [row["rule"] for row in data["findings"]]
    assert "rest of the repository" in repo.occam("scan", "only", "--isolated").stdout


def test_scan_isolated_with_a_diff(repo):
    repo.write("only/a.py", "x = 1\n")
    repo.commit()
    repo.write("only/a.py", "x = 1\nimport requests\nrequests.get('http://x.invalid')\n")
    data = json.loads(repo.occam("scan", "--isolated", "--changed", "--format", "json").stdout)
    assert data["stats"]["files"] == 1 and "missing-timeout" in [row["rule"] for row in data["findings"]]


def test_map_points_at_queries_and_can_stay_isolated(repo):
    assert "occam query" in repo.occam("map").stdout
    assert repo.occam("map", "app", "--isolated").returncode == 0


def test_tools_see_a_language_past_the_first_twenty_thousand_files(monkeypatch, tmp_path):
    monkeypatch.setattr(toolrun.filesystem, "list_files", lambda *args: [f"a{i}.py" for i in range(20_001)] + ["late/main.go"])
    monkeypatch.setattr(toolrun.filesystem, "load_config", lambda *args: {})
    assert "go" in toolrun._languages_here(tmp_path)


def test_tools_narrow_to_named_paths(tmp_path):
    (tmp_path / "sub").mkdir()
    assert toolrun._scoped(["ruff", "check", "."], tmp_path, [str(tmp_path / "sub")]) == ["ruff", "check", "./sub"]
    assert toolrun._scoped(["ruff", "check", "."], tmp_path, None) == ["ruff", "check", "."]
    assert toolrun._scoped(["cargo", "clippy"], tmp_path, [str(tmp_path / "sub")]) == ["cargo", "clippy"]


@pytest.mark.skipif(not shutil.which("ruff"), reason="ruff isn't installed")
def test_tools_run_really_narrows(repo):
    repo.write("a/one.py", "import os\n")
    repo.write("b/two.py", "import sys\n")
    done = repo.occam("tools", "--run", "--only", "ruff", "a")
    assert "ruff: exit 1, 1 results" in done.stdout


def fake_tool(repo, tmp_path, name, body):
    """A stand-in on PATH, outside the repository, so it runs without --allow-exec."""
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(body)
    (folder / name).chmod(0o755)
    repo.env["PATH"] = f"{folder}{os.pathsep}{os.environ['PATH']}"
    repo.write("a.py", "x = 1\n")


@pytest.mark.parametrize("body, code, says", [
    ("#!/bin/sh\necho '[]'\nexit 2\n", 1, "error"),  # ruff's own failure, which isn't a finding
    ("#!/bin/sh\nkill -9 $$\n", 1, "signal"),
    ("#!/nonexistent/interpreter\n", 1, "failed to start"),
    ("#!/bin/sh\necho '[{}]'\nexit 1\n", 0, "exit 1, 1 results"),  # findings
])
def test_tools_run_exits_nonzero_only_when_a_tool_failed(repo, tmp_path, body, code, says):
    fake_tool(repo, tmp_path, "ruff", body)
    done = repo.occam("tools", "--run", "--only", "ruff")
    assert done.returncode == code and says in done.stdout, done.stdout


def test_a_tool_that_runs_out_of_time_stops_what_it_started(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    script = tmp_path / "slow.sh"
    script.write_text(f"#!/bin/sh\n(sleep 2; touch {marker}) &\nwait\n")
    script.chmod(0o755)
    monkeypatch.setattr(toolrun, "TIMEOUT_SECONDS", 1)
    line, finished = toolrun._run_one(toolrun.CATALOG[0], [str(script)], tmp_path, None)
    assert "timed out" in line.lower() and not finished
    time.sleep(2.5)
    assert not marker.exists()


def test_an_unknown_only_name_is_refused(repo):
    done = repo.occam("tools", "--run", "--only", "ruff", "--only", "nosuchtool")
    assert done.returncode == 2 and "nosuchtool" in done.stdout and "golangci-lint" in done.stdout


@pytest.mark.parametrize("name, sub, expected", [
    ("golangci-lint", "pkg", "./pkg/..."), ("govulncheck", "pkg", "./pkg/..."), ("ruff", "pkg", "./pkg"), ("golangci-lint", "pkg/main.go", "./pkg"),
])
def test_each_tool_narrows_the_way_it_takes_paths(tmp_path, name, sub, expected):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "main.go").write_text("package main\n")
    tool = next(tool for tool in toolrun.CATALOG if tool.name == name)
    command, note = toolrun._invocation(tool, name, tmp_path, [str(tmp_path / sub)])
    assert expected in command and note is None


@pytest.mark.parametrize("name", ["tsc", "knip", "gitleaks", "deadcode", "cargo", "actionlint"])
def test_a_tool_that_cant_be_narrowed_says_it_read_everything(tmp_path, name):
    (tmp_path / "pkg").mkdir()
    tool = next(tool for tool in toolrun.CATALOG if tool.name == name)
    command, note = toolrun._invocation(tool, name, tmp_path, [str(tmp_path / "pkg")])
    assert "./pkg" not in " ".join(command) and "whole repository" in note


def test_the_whole_repository_note_reaches_the_report(repo, tmp_path):
    fake_tool(repo, tmp_path, "actionlint", "#!/bin/sh\nexit 0\n")
    (repo.path / "sub").mkdir()
    done = repo.occam("tools", "--run", "--only", "actionlint", "sub")
    assert "whole repository" in done.stdout


def test_a_saved_tool_run_says_how_it_was_run(repo, tmp_path):
    fake_tool(repo, tmp_path, "ruff", "#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'ruff 9.9'; exit 0; fi\necho '[]'\n")
    repo.occam("tools", "--run", "--only", "ruff")
    [saved] = list((tmp_path / "state").rglob("tools/ruff.json"))
    envelope = json.loads(saved.read_text())
    assert envelope["exit"] == 0 and envelope["args"][-1] == "." and envelope["cwd"] == str(repo.path.resolve())
    assert envelope["version"] == "ruff 9.9" and envelope["stdout"] == "[]\n" and envelope["seconds"] >= 0 and envelope["started"]
    assert envelope["command"].endswith("ruff")


def test_a_script_with_no_extension_is_told_by_its_shebang(tmp_path):
    (tmp_path / "x").write_text("#!/bin/bash\n")
    (tmp_path / "y").write_text("#!/usr/bin/env python3\n")
    (tmp_path / "z").write_text("plain\n")
    assert query.language_at(tmp_path, "x") == "shell" and query.language_at(tmp_path, "y") == "python" and query.language_at(tmp_path, "z") is None


BLANKS = "\n" * 1_400_000
HANGS = {
    "Main.java": BLANKS, "m.c": BLANKS, "lib.rs": BLANKS, "main.go": BLANKS, "deep.sh": "#!/bin/sh\n" + BLANKS,
    "Cargo.toml": BLANKS, "Dockerfile": BLANKS,
    "setup.py": "a" * 1_400_000,
    "tox.ini": "[testenv:a]\n" * 110_000,
    "loops.sh": "#!/bin/sh\n" + "for a in " * 150_000 + "\n",
    "opens.py": "open(" * 280_000 + "os.remove(x)\n",
    "words.java": "public " + "a " * 700_000 + "\n",
}


@pytest.mark.parametrize("args", ALL_QUERIES + (("outline", "Main.java", "m.c", "lib.rs", "main.go", "deep.sh", "loops.sh", "opens.py", "words.java"),), ids=lambda args: " ".join(args)[:30])
def test_a_hostile_file_cant_hang_a_query(tmp_path, args):
    """Each file is shaped to make a careless expression take quadratic time. The timeout in Repo.occam is what would fail this."""
    repo = make_repo(tmp_path / "r", tmp_path / "s")
    for name, content in HANGS.items():
        repo.write(name, content)
    repo.commit("hostile")
    done = repo.occam("query", *args, "--top", "1")
    assert done.returncode == 0, done.stdout[:300]


def test_a_hostile_shell_file_cant_hang_a_scan(tmp_path):
    repo = make_repo(tmp_path / "r", tmp_path / "s")
    for name in ("deep.sh", "loops.sh"):
        repo.write(name, HANGS[name])
    repo.commit("hostile")
    assert repo.occam("scan", "deep.sh", "loops.sh", "--isolated").returncode == 0


def test_mutate_reports_a_line_even_if_the_file_shrank_during_the_run(tmp_path, monkeypatch):
    from occam_tools import verify
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.write("a.py", "def f(x):\n    return x + 1\n")
    repo.write("tests/test_a.py", "def test_nothing():\n    assert True\n")
    repo.git("init", "-q")
    repo.commit()
    monkeypatch.setenv("OCCAM_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setattr(verify, "_tests_really_use", lambda *args: True)

    def edited_meanwhile(*args) -> str:
        (repo.path / "a.py").write_text("")
        return "passed"

    monkeypatch.setattr(verify, "_try_mutant", edited_meanwhile)
    text, code = verify.mutate(repo.path, f"{sys.executable} -c pass", [str(repo.path / "a.py")], False, None, 3, 30)
    assert code == 1 and "return x + 1" in text


def test_query_functions_helper_is_importable_without_a_repository():
    assert query_code._first_line("One line.\n\nMore.") == "One line."
