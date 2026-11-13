"""occam.sh, run for real under each bash here, and compared with occam.py on the same repositories."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sh_support import BASHES, FILES, GIT, SCRIPTS, SOURCE, TOKEN, TOOL, Repo, make_repo

from occam_tools import files as filesystem, source

@pytest.fixture(params=BASHES)
def bash(request):
    return request.param


@pytest.fixture
def repo(tmp_path, bash):
    return make_repo(tmp_path / "repo", tmp_path / "state", bash)


@pytest.fixture
def plain(tmp_path, bash):
    return make_repo(tmp_path / "plain", tmp_path / "state", bash, git=False)


# ---------------------------------------------------------------- the two tools can't drift

def _array(name: str) -> list[str]:
    body = re.search(rf"^{name}=\((.*?)\)$", SOURCE, re.M | re.S).group(1)
    return body.split()


def _value(name: str) -> str:
    return re.search(rf"^{name}='([^\n]*)'$", SOURCE, re.M).group(1)


def test_git_safety_flags_match_occam_tools():
    assert _array("GIT_SAFETY") == filesystem._GIT_SAFETY


def test_git_environment_matches_occam_tools():
    exported = dict(pair.split("=", 1) for pair in re.search(r"^export (GIT_OPTIONAL_LOCKS.*)$", SOURCE, re.M).group(1).split())
    assert exported == filesystem._GIT_ENVIRONMENT


def test_driver_key_matches_occam_tools():
    assert _value("DRIVER_KEY").split(r"\..*\.") == filesystem._DRIVER_KEY.pattern.split(r"\.(.*)\.")


def _posix(pattern: str) -> str:
    return pattern.replace(r"\w+", "[A-Za-z0-9_]+")


def test_what_counts_as_vendored_generated_and_tests_matches_occam_tools():
    assert _value("VENDORED") == _posix(filesystem.VENDORED.pattern)
    assert _value("GENERATED") == _posix(filesystem.GENERATED_NAMES.pattern)
    assert _value("TEST_PATH") == _posix(source.TEST_PATH.pattern)


def test_language_table_matches_occam_tools():
    assert dict(pair.split("=") for pair in _value("EXTENSIONS").split()) == source.EXTENSIONS


def test_skipped_folders_match_occam_tools():
    assert set(_value("SKIP_DIRS").split()) == filesystem.SKIP_DIRS


# ---------------------------------------------------------------- portability and style of the script itself

def test_script_parses_on_every_bash_here(bash):
    assert subprocess.run([bash, "-n", str(TOOL)], capture_output=True).returncode == 0


def test_script_avoids_what_bash_3_2_or_bsd_tools_lack():
    code = "\n".join(line for line in SOURCE.split("\n") if not line.lstrip().startswith("#"))
    for forbidden in (r"\bmapfile\b", r"\breadarray\b", r"declare -A", r"\$\{\w+,,\}", r"\$\{\w+\^\^\}", r"\bsed -i\b", r"\bgrep -P\b", r"\breadlink -f\b", r"\bstat -c\b", r"\bwc -L\b"):
        assert not re.search(forbidden, code), forbidden


SHELLCHECK = shutil.which("shellcheck")


@pytest.mark.skipif(not SHELLCHECK, reason="shellcheck isn't installed")
def test_shellcheck_passes():
    """Every finding, notes included: the ones that are meant say so where they are."""
    done = subprocess.run([SHELLCHECK, "--shell=bash", str(TOOL)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout


def test_occams_own_scanner_finds_no_defects_in_it():
    sys.path.insert(0, str(SCRIPTS))
    from occam_tools import scan
    serious = [f for f in scan.scan_text("occam.sh", SOURCE) if f["severity"] in ("critical", "high") and f["rule"] not in ("hardcoded-secret",)]
    assert not serious, serious


# ---------------------------------------------------------------- size, against occam.py

def _sh_size(output: str) -> tuple[int, int]:
    match = re.match(r"(\d+) lines in (\d+) code files", output)
    return int(match.group(1)), int(match.group(2))


def _sh_folders(output: str) -> dict[str, int]:
    return {match.group(2): int(match.group(1)) for match in re.finditer(r"^ +(\d+) +\d+ +\S+  (\S.*)$", output, re.M)}


@pytest.mark.parametrize("arguments", [(), ("app",), ("tests", "bin/run"), ("--depth", "2")], ids=lambda a: " ".join(a) or "all")
def test_size_agrees_with_occam_py(repo, arguments):
    from_py = repo.py("size", *arguments, "--top", "100")
    output = repo.sh("size", *arguments, "--top", "100").stdout
    assert _sh_size(output) == (from_py["lines"], from_py["files"])
    assert _sh_folders(output) == {row["path"]: row["lines"] for row in from_py["directories"]}


def test_size_agrees_with_occam_py_on_a_plain_folder(plain):
    from_py = plain.py("size", "--top", "100")
    assert _sh_size(plain.sh("size", "--top", "100").stdout) == (from_py["lines"], from_py["files"])


def test_size_leaves_out_vendored_ignored_and_configured_files(repo):
    output = repo.sh("size", "--top", "100").stdout
    for name in ("vendor/lib.py", "dist/out.min.js", "fixtures/skipped.py", "a.skipme.py"):
        assert name not in output


def test_size_handles_awkward_names(repo):
    output = repo.sh("size", "--top", "100").stdout
    for name in ("app/spaced name.py", "app/-dash.py", "app/ünicode.py", "bin/run"):
        assert name in output


def test_size_reads_a_file_named_outright_even_if_ignored(repo):
    from_py = repo.py("size", "fixtures/skipped.py")
    assert _sh_size(repo.sh("size", "fixtures/skipped.py").stdout) == (from_py["lines"], from_py["files"]) == (1, 1)


def test_size_skips_symlinks_and_deleted_files(repo):
    (repo.path / "link.py").symlink_to("app/core.py")
    repo.commit("link")
    (repo.path / "app/api.py").unlink()
    from_py = repo.py("size", "--top", "100")
    assert _sh_size(repo.sh("size", "--top", "100").stdout) == (from_py["lines"], from_py["files"])
    assert "app/api.py" not in repo.sh("size", "--top", "100").stdout


def test_size_includes_new_untracked_files(repo):
    repo.write("app/new.py", "a = 1\n")
    assert "app/new.py" in repo.sh("size", "--top", "100").stdout


def test_size_says_what_it_left_out_for_its_name(repo):
    repo.write("app/tab\tname.py", "a = 1\n")
    output = repo.sh("size").stdout
    assert "Left out 1 files whose names need quoting" in output
    assert _sh_size(output)[1] == repo.py("size")["files"] - 1


def test_size_of_an_empty_repository(tmp_path, bash):
    (tmp_path / "e").mkdir()
    repo = Repo(tmp_path / "e", tmp_path / "s", bash)
    repo.git("init", "-q")
    done = repo.sh("size")
    assert done.returncode == 0 and done.stdout.startswith("0 lines in 0 code files")


def test_output_is_bounded(repo):
    output = repo.sh("size", "--top", "1").stdout
    assert "Raise --top" in output


def test_runs_from_a_subfolder(repo):
    assert repo.sh("size", ".", cwd=repo.path / "app").stdout == repo.sh("size", "app").stdout


# ---------------------------------------------------------------- find and grep

def test_find_totals_agree_with_occam_py(repo):
    assert re.match(r"'total': (\d+) lines in (\d+) files", repo.sh("find", "total").stdout).groups() == (str(repo.py("find", "total")["total"]), str(repo.py("find", "total")["files"]))


def test_find_sorts_what_text_can_show(repo):
    output = repo.sh("find", "total", "--top", "100").stdout
    defined, _, rest = output.partition("Imported")
    assert "app/core.py:1" in defined and "app/api.py:1" in rest
    assert "tests/test_core.py" in output.partition("In tests")[2]


def test_find_gives_the_same_answer_in_a_plain_folder(repo, tmp_path, bash):
    other = make_repo(tmp_path / "plain2", tmp_path / "s2", bash, git=False)
    assert repo.sh("find", "total", "--top", "100").stdout == other.sh("find", "total", "--top", "100").stdout


def test_find_matches_whole_words_and_takes_regex_characters_literally(repo):
    repo.write("app/odd.py", "subtotal = 1\ntotal_cost = 2\nd = 'a.b'\n")
    assert "app/odd.py" not in repo.sh("find", "total", "--top", "100").stdout
    repo.write("app/lit.py", "star_x = 1\nstarxy = 2\n")
    assert "app/lit.py" not in repo.sh("find", "star.x", "--top", "100").stdout.partition("Looks defined")[2].partition("Used")[0]
    assert repo.sh("find", "a(b", "--top", "100").returncode == 0


def test_a_name_with_no_hits_is_a_clean_answer(repo):
    done = repo.sh("find", "nothing_at_all_here")
    assert done.returncode == 0 and "0 lines in 0 files" in done.stdout


def test_find_withholds_a_credential(repo):
    repo.write("app/conf.py", f'total = "{TOKEN}"\n')
    output = repo.sh("find", "total", "--top", "100").stdout
    assert TOKEN not in output and "withheld" in output


def test_grep_counts_and_narrows(repo):
    assert repo.sh("grep", "def t[a-z]+").stdout.startswith("3 matching lines in 3 files")
    assert repo.sh("grep", "def t[a-z]+", "tests").stdout.startswith("2 matching lines in 2 files")
    assert repo.sh("grep", "DEF T", "-i", "tests").stdout.startswith("2 matching")


def test_grep_withholds_a_credential(repo):
    repo.write("app/conf.py", f'password = "s3cr3tvalue"\nkey = "{TOKEN}"\nurl = "postgres://u:hunter2hunter@db.invalid/x"\n')
    output = repo.sh("grep", "s3cr3t|ghp_|hunter2", "--top", "100").stdout
    assert "s3cr3tvalue" not in output and TOKEN not in output and "hunter2" not in output and output.count("withheld") == 3


def test_grep_on_a_folder_searches_only_files_that_count(plain):
    assert "vendor/lib.py" not in plain.sh("grep", "total", "--top", "100").stdout
    assert plain.sh("grep", "zzz_not_here").stdout.startswith("0 matching")


def test_a_bad_expression_is_an_error_not_a_clean_answer(repo):
    done = repo.sh("grep", "(")
    assert done.returncode == 2 and "Nothing was checked" in done.stdout


# ---------------------------------------------------------------- history

@pytest.fixture
def busy(repo):
    for index in range(3):
        repo.write("app/core.py", FILES["app/core.py"] + f"\n# {index}\n")
        repo.write("app/api.py", FILES["app/api.py"] + f"\n# {index}\n")
        repo.commit(f"fix something {index}", author="Bea" if index else "Ann")
    return repo


def test_history_agrees_with_occam_py(busy):
    from_py = busy.py("history", "--top", "100")
    output = busy.sh("history", "--top", "100").stdout
    assert output.startswith(f"{from_py['commits_read']} commits.")
    assert f"{from_py['bus_factor']} of them account for over half" in output
    for row in from_py["files"]:
        assert re.search(rf"^ +{row['commits']}  \[{row['fix_commits']} fix\]  {row['authors']} people  {re.escape(row['path'])}$", output, re.M), row


def test_history_of_one_file_shows_commits_and_partners(busy):
    output = busy.sh("history", "app/core.py").stdout
    assert "[fix] fix something 2" in output and "Changed together" in output and "app/api.py" in output


def test_history_of_a_folder_stays_in_it(busy):
    output = busy.sh("history", "tests", "--top", "100").stdout
    assert "tests/test_core.py" in output and "app/core.py" not in output.partition("Most changed")[2]


def test_history_limits(busy):
    assert "Raise --commits" in busy.sh("history", "--commits", "1").stdout
    assert busy.sh("history", "--since", "2098-01-01").stdout.startswith("No commits found")


def test_history_outside_git_exits_2(plain):
    done = plain.sh("history")
    assert done.returncode == 2 and "Nothing was checked" in done.stdout


def test_history_keeps_a_credential_in_a_message_out(repo):
    repo.write("x.py", "x = 1\n")
    repo.commit(f"rotate {TOKEN}")
    assert TOKEN not in repo.sh("history", "x.py").stdout


def test_history_says_a_shallow_clone_is_cut_short(busy, tmp_path, bash):
    clone = tmp_path / "clone"
    subprocess.run([GIT, "clone", "-q", "--depth", "1", f"file://{busy.path}", str(clone)], check=True, env=busy.env)
    assert "shallow clone" in Repo(clone, tmp_path / "s3", bash).sh("history").stdout


# ---------------------------------------------------------------- leaks

def test_leaks_finds_what_was_deleted_and_withholds_it(repo):
    repo.write("app/conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    repo.write("app/conf.py", "KEY = None\n")
    repo.commit("remove")
    output = repo.sh("leaks").stdout
    assert "app/conf.py" in output and TOKEN not in output and "credential-shaped lines: 1." in output


def test_leaks_agrees_with_occam_py_on_shapes_and_placeholders(repo):
    repo.write("app/a.py", 'password = "hunter2hunter2"\n')
    repo.write("app/b.py", 'password = "changeme"\n')
    repo.write("app/c.py", 'url = "postgres://u:realpassvalue@db.invalid/x"\n')
    repo.write("tests/d.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    from_py = {row["path"] for row in repo.py("leaks")["rows"]}
    output = repo.sh("leaks").stdout
    assert from_py == {"app/a.py", "app/c.py"}
    assert all(path in output for path in from_py) and "app/b.py" not in output and "tests/d.py" not in output


def test_leaks_says_when_it_stopped_short(repo):
    repo.write("x.py", "x = 1\n")
    repo.commit("more")
    assert "Raise --commits" in repo.sh("leaks", "--commits", "1").stdout


# Token-shaped values are split so no credential shape sits in the repository, where secret scanners block a push.
CREDENTIALS = ['password = "sunshine"', 'db_password = "mysecretprod1"', 'password: str = "Xk9mQ2vLp7"', 'os.getenv("API_KEY", "Xk9mQ2vLp7aa")', "API_KEY=Xk9mQ2vLp7bb",
               "aws_secret_access_key = wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY", 'PASSWORD = "correct horse battery"', 'url = "postgres://admin:p%40ss%21word@db/x"',
               "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7", 'key = "AKIAIOSFODNN7EXAMPLE"\t# a tab before this', 'token = "abc def"  \t# tab',
               'DB_PASS = "sunshine"', 'pass: "sunshine"', "password=Tr0ub4dor$3", 'password = b"sunshine"', "PASSWORD=correcthorsebatterystaple", "u = redis://:Xk9mQ2vLp7@cache:6379/0",
               "u = https://Xk9mQ2vLp7aaa@github.com/x", "Authorization: Bearer Xk9mQ2vLp7aaa", "run --password sunshine", "sk_live" + "_Xk9mQ2vLp7aaaaaaaaaaaa", "glpat" + "-Xk9mQ2vLp7aaaaaaaaaa",
               "github_pat" + "_Xk9mQ2vLp7aaaaaaaaaaaaaa", "AS" + "IAXK9MQ2VLP7AAAAAA", 'set_password("sunshine")', "export DB_PASSWORD=SUNSHINEPASSWORD", "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\r"]
SECRET_PIECES = ["sunshine", "SUNSHINE", "mysecretprod1", "Xk9mQ2vLp7", "wJalr", "correct horse", "correcthorse", "p%40ss", "MIIEvQ", "AKIAIOSFODNN7EXAMPLE", "abc def", "Tr0ub4dor", "ASIAXK9"]


@pytest.mark.parametrize("line", CREDENTIALS, ids=lambda line: line[:18])
def test_grep_find_and_commands_withhold_each_shape(repo, line):
    repo.write("app/conf.py", f"needle = 1\n{line}\n")
    repo.write("Makefile", f"build:\n\t{line}\n")
    found = repo.sh("grep", "sunshine|SUNSHINE|mysecret|Xk9m|XK9M|wJalr|horse|ss%21|MIIEvQ|AKIA|abc def|Tr0ub", "--top", "100").stdout
    assert not [piece for piece in SECRET_PIECES if piece in found], found
    assert "withheld" in found


def test_code_stays_readable_where_nothing_is_assigned(repo):
    lines = ["token = new_token", "password = get_password()", "def check(password):", "x = 'http://localhost:8080/x'", "max_tokens = 1024", "def login(token: Token, user: User):", "api_key=settings.API_KEY,",
             "accessToken: accessToken,", "self._token = None", "pwd = None", "page_token=None,", "token_count = 0", "password_min_length = 8", "if token==END:", "ssh://git@github.com/x"]
    repo.write("app/conf.txt", "\n".join(lines) + "\n")
    output = repo.sh("grep", ".", "app/conf.txt", "--top", "100").stdout
    assert "withheld" not in output, output


def test_each_sed_expression_fits_the_line_limit_of_bsd_sed(tmp_path):
    """Past 2048 characters BSD sed reports unbalanced brackets, and on GNU tools nothing at all goes wrong, so only this catches it there."""
    start, end = SOURCE.index("TAB=$(printf"), SOURCE.index("SUPPRESSIONS=")
    kept = [line for line in SOURCE[start:end].split("\n") if re.match(r"(TAB|SOH|CR|SECRET_\w+|VALUE_\w+|URL_PASSWORD|KEY_BODY)=", line)]
    names = ("SECRET_TOKENS", "SECRET_QUOTED", "SECRET_BARE", "SECRET_DEFAULT", "SECRET_ENV", "SECRET_CALL", "SECRET_FLAG", "SECRET_BEARER", "URL_PASSWORD", "KEY_BODY")
    probe = tmp_path / "probe.sh"
    probe.write_text("\n".join([*kept, *(f'echo "${{#{name}}}"' for name in names)]) + "\n")
    lengths = [int(line) for line in subprocess.run(["bash", str(probe)], capture_output=True, text=True, check=True).stdout.split()]
    assert len(lengths) == len(names) and max(lengths) < 1800, lengths


def test_a_file_name_cant_get_its_lines_withheld(repo):
    repo.write(".github/workflows/secret-scan-A1.yml", "jobs:\n  a:\n    steps:\n      - run: make check\n")
    assert "make check" in repo.sh("commands", "--top", "100").stdout


def test_leaks_agrees_with_occam_py_on_what_a_placeholder_is(repo):
    repo.write("app/real1.py", 'PASSWORD = "Pa$$w0rd!2024"\n')
    repo.write("app/real2.py", 'API_KEY = "9f8a7TeSt3b2c1d0e9f8a7b6c5"\n')
    repo.write("app/real3.py", 'db_password = "Latest!2024q"\n')
    repo.write("app/real4.py", 'password = "kj3{h4}5kj"\n')
    repo.write("app/real5.py", "u = redis://:Xk9mQ2vLp7@cache:6379/0\n")
    repo.write("app/not1.py", 'password = "changeme"\n')
    repo.write("app/not2.py", 'password = "${DB_PASS}"\n')
    repo.write("app/not3.py", "max_tokens = 1024\n")
    repo.write("app/not4.py", 'password = "test"\n')
    repo.commit("add")
    from_py = {row["path"] for row in repo.py("leaks", "--top", "100")["rows"]}
    output = repo.sh("leaks", "--top", "100").stdout
    assert from_py == {f"app/real{i}.py" for i in range(1, 6)}
    assert {path for path in (f"app/{name}.py" for name in ("real1", "real2", "real3", "real4", "real5", "not1", "not2", "not3", "not4")) if path in output} == from_py


def test_leaks_reads_past_a_nul(repo):
    (repo.path / "nul.txt").write_bytes(b'x\0KEY = "' + TOKEN.encode() + b'"\n')
    repo.commit("add")
    assert "nul.txt" in repo.sh("leaks").stdout


def test_leaks_cant_be_hidden_by_merge_settings_or_replaced_commits(repo):
    repo.write("a.py", f'KEY = "{TOKEN}"\n')
    repo.commit("a commit that gets hidden")
    repo.write("b.py", "x = 1\n")
    repo.commit("next")
    repo.git("config", "log.diffMerges", "off")
    repo.git("replace", "--graft", "HEAD", "HEAD~2")
    assert "a.py" in repo.sh("leaks").stdout


def test_leaks_says_a_shallow_clone_is_cut_short(repo, tmp_path, bash):
    repo.write("x.py", "x = 1\n")
    repo.commit("more")
    clone = tmp_path / "clone"
    subprocess.run([GIT, "clone", "-q", "--depth", "1", f"file://{repo.path}", str(clone)], check=True, env=repo.env)
    assert "shallow clone" in Repo(clone, tmp_path / "s3", bash).sh("leaks").stdout


def test_a_container_command_cant_print_a_credential(repo):
    repo.write("Dockerfile", 'FROM x\nCMD ["run", "--password=Xk9mQ2vLp7"]\n')
    repo.write("Procfile", "web: PASSWORD=Xk9mQ2vLp7 run\n")
    output = repo.sh("entry", "--top", "100").stdout
    assert "Dockerfile" in output and "Xk9mQ2vLp7" not in output.replace("(line withheld", "")


def test_a_very_long_line_is_cut(repo):
    repo.write("Makefile", "build:\n\tok\n" + "target" + "x" * 5000 + ":\n")
    repo.write("Procfile", "web: run " + "y" * 5000 + "\n")
    assert len(max(repo.sh("commands", "--top", "100").stdout.split("\n"), key=len)) < 400
    assert len(max(repo.sh("entry", "--top", "100").stdout.split("\n"), key=len)) < 400


# ---------------------------------------------------------------- settings a repository can use to make a failure look clean

@pytest.mark.parametrize("key, value", [("color.ui", "always"), ("color.grep", "always"), ("grep.column", "true"), ("grep.fullName", "true"), ("grep.lineNumber", "false")])
def test_grep_settings_cant_hide_a_match(repo, key, value):
    repo.git("config", key, value)
    assert repo.sh("find", "total").stdout.startswith("'total': 9 lines")
    assert "focused-test: 1 in 1 files" in repo.sh("markers").stdout


@pytest.mark.parametrize("attributes", ["* -diff\n", "* binary\n", "* -text\n"])
def test_attributes_cant_hide_a_match_or_a_leak(repo, attributes):
    repo.write(".gitattributes", attributes)
    repo.write("app/conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    assert repo.sh("find", "total").stdout.startswith("'total': 9 lines")
    assert "app/conf.py" in repo.sh("leaks").stdout


def test_a_real_binary_stays_out_of_search(repo):
    (repo.path / "blob.dat").write_bytes(b"total\0total\n")
    assert "blob.dat" not in repo.sh("grep", "total", "--top", "100").stdout


@pytest.mark.parametrize("key, value", [("core.bigFileThreshold", "1"), ("log.showRoot", "false"), ("i18n.logOutputEncoding", "UTF-16"), ("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"), ("color.diff", "always"), ("color.ui", "always")])
def test_settings_cant_hide_history_or_leaks(tmp_path, bash, key, value):
    repo = make_repo(tmp_path / "r", tmp_path / "s", bash)
    repo.write("app/conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    repo.git("config", key, value)
    assert "app/conf.py" in repo.sh("leaks").stdout
    assert repo.sh("history").stdout.startswith("2 commits.")


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
    output = repo.sh("leaks", "--top", "100").stdout
    for path in ("a.py", 'ev"il.py', "new.py", "side.py"):
        assert path in output, path
    assert TOKEN not in output


def test_leaks_reads_a_secret_added_in_a_merge(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.py", "x = 1\n")
    repo.commit("side")
    repo.git("checkout", "-q", "-")
    repo.git("merge", "-q", "--no-ff", "--no-commit", "side")
    repo.write("merged.py", f'KEY = "{TOKEN}"\n')
    repo.commit("merge")
    assert "merged.py" in repo.sh("leaks").stdout


# ---------------------------------------------------------------- links, odd names and files that never end

def test_a_link_cant_print_what_it_points_at(repo, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("web: SECRET_OUTSIDE_LINE\n")
    (repo.path / "Procfile").symlink_to(outside)
    (repo.path / "Makefile").unlink()
    (repo.path / "Makefile").symlink_to(outside)
    assert "SECRET_OUTSIDE_LINE" not in repo.sh("entry", "--top", "100").stdout
    assert "SECRET_OUTSIDE_LINE" not in repo.sh("commands", "--top", "100").stdout


def test_a_link_to_a_device_cant_hang_size(repo):
    (repo.path / "evil.py").symlink_to("/dev/zero")
    done = repo.sh("size", "--top", "100")
    assert done.returncode == 0


def test_a_tracked_file_swapped_for_a_link_counts_nothing(repo, tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("x\n" * 5000)
    (repo.path / "app/core.py").unlink()
    (repo.path / "app/core.py").symlink_to(big)
    assert _sh_size(repo.sh("size", "--top", "100").stdout)[0] < 100


@pytest.mark.parametrize("folder", ["a=b", "-dash", "sp ace"])
def test_a_folder_name_cant_cut_a_list_short(repo, folder):
    repo.write(f"{folder}/Makefile", "alpha:\n\tgo\n")
    repo.write(f"{folder}/Dockerfile", 'CMD ["alpha"]\n')
    repo.write("zz/Makefile", "omega:\n\tgo\n")
    repo.write("zz/Dockerfile", 'CMD ["omega"]\n')
    commands = repo.sh("commands", "--top", "100").stdout
    entry = repo.sh("entry", "--top", "100").stdout
    assert "make alpha" in commands and "make omega" in commands
    assert "alpha" in entry and "omega" in entry


def test_a_file_named_like_a_commit_marker_is_only_a_file(repo):
    repo.write("@@@fake", "x\n")
    repo.commit("add")
    assert repo.sh("history").stdout.startswith("2 commits.")


def test_a_config_that_never_ends_cant_hang_the_tool(repo, tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    repo.git("config", "core.excludesFile", str(fifo))
    done = subprocess.run([repo.bash, str(TOOL), "size"], cwd=repo.path, env={**repo.env, "OCCAM_TIMEOUT": "2"}, capture_output=True, text=True, timeout=30)
    assert done.returncode == 2 and "Nothing was checked" in done.stdout


def test_the_watchdog_doesnt_outlive_the_answer(repo):
    started = subprocess.run([repo.bash, str(TOOL), "doctor"], cwd=repo.path, env={**repo.env, "OCCAM_TIMEOUT": "60"}, capture_output=True, text=True, timeout=20)
    assert started.returncode == 0


def test_a_working_tree_elsewhere_is_refused(repo, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "other.py").write_text("total = 1\n")
    repo.git("config", "core.worktree", str(elsewhere))
    done = repo.sh("grep", "total")
    assert done.returncode == 2 and "other.py" not in done.stdout


def test_a_working_tree_in_a_parent_is_refused(tmp_path, bash):
    home = tmp_path / "home"
    repo = make_repo_inside(home, tmp_path, bash)
    (home / "notes.txt").write_text("SECRETMARK\n")
    repo.git("config", "core.worktree", str(home))
    done = repo.sh("grep", "SECRETMARK")
    assert done.returncode == 2 and "notes.txt" not in done.stdout


def make_repo_inside(home: Path, tmp_path: Path, bash: str) -> Repo:
    (home / "dl").mkdir(parents=True)
    return make_repo(home / "dl" / "evil", tmp_path / "s", bash)


def test_setups_that_are_fine_stay_fine(repo, tmp_path, bash):
    linked = tmp_path / "linked"
    repo.git("worktree", "add", "-q", str(linked))
    assert Repo(linked, tmp_path / "s4", bash).sh("size").returncode == 0
    (tmp_path / "ln").symlink_to(repo.path)
    assert repo.sh("size", cwd=tmp_path / "ln").returncode == 0
    assert repo.sh("size", cwd=repo.path / ".git").returncode in (0, 2)
    other_git = tmp_path / "sep"
    subprocess.run([GIT, "init", "-q", f"--separate-git-dir={tmp_path / 'sep.git'}", str(other_git)], check=True, env=repo.env)
    (other_git / "a.py").write_text("x = 1\n")
    assert Repo(other_git, tmp_path / "s5", bash).sh("size").returncode == 0


def test_a_bare_repository_says_so(tmp_path, bash):
    bare = tmp_path / "bare.git"
    subprocess.run([GIT, "init", "-q", "--bare", str(bare)], check=True)
    done = subprocess.run([bash, str(TOOL), "grep", "x"], cwd=bare, capture_output=True, text=True, timeout=30)
    assert done.returncode == 2 and "bare" in done.stdout


# ---------------------------------------------------------------- how the script ends

def test_nothing_is_written_to_stderr_on_a_normal_run(repo):
    for args in (("doctor",), ("grep", "total"), ("size",), ("nosuch",)):
        assert repo.sh(*args).stderr == "", args


def _processes() -> list[tuple[int, int, str]]:
    """Other sessions' command lines can hold anything, including line breaks and bytes that aren't text."""
    lines = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, errors="replace").stdout.split("\n")
    rows = (line.split(None, 2) for line in lines)
    return [(int(row[0]), int(row[1]), row[2]) for row in rows if len(row) == 3 and row[0].isdecimal() and row[1].isdecimal()]


def _tree_of(root: int) -> dict[int, str]:
    """Every process under `root`. Found by ancestry, since other sessions run copies of these tests and a killed run leaves its processes behind."""
    table = _processes()
    found = {root}
    while True:
        more = {pid for pid, parent, _ in table if parent in found} - found
        if not more:
            return {pid: command for pid, _, command in table if pid in found}
        found |= more


def _still_running(started: dict[int, str]) -> dict[int, str]:
    """Comparing the command means a reused PID can't count."""
    return {pid: command for pid, _, command in _processes() if started.get(pid) == command}


def test_nothing_stays_running_after_an_answer(repo):
    import random
    import signal
    watchdog = f"sleep {random.randrange(10_000_000, 99_999_999)}"
    repo.sh("size", env={**repo.env, "OCCAM_TIMEOUT": watchdog.split()[1]})
    left = [pid for pid, _, command in _processes() if command == watchdog]
    for pid in left:
        os.kill(pid, signal.SIGKILL)
    assert not left


@pytest.mark.parametrize("name, status", [("TERM", 143), ("HUP", 129), ("INT", 130)])
def test_a_signal_stops_everything_and_doesnt_claim_a_timeout(repo, tmp_path, name, status):
    import signal
    import time
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    repo.git("config", "core.excludesFile", str(fifo))
    number = getattr(signal, f"SIG{name}")
    # Bash can't trap a signal that was ignored when it started, as one is under nohup or in a background job, so reset it.
    # A short timeout bounds what's left if pytest itself gets killed.
    process = subprocess.Popen([repo.bash, str(TOOL), "size"], cwd=repo.path, env={**repo.env, "OCCAM_TIMEOUT": "300"}, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True, preexec_fn=lambda: signal.signal(number, signal.SIG_DFL))
    started = {process.pid: ""}
    try:
        time.sleep(1.5)
        started = _tree_of(process.pid)
        assert any(command.startswith("sleep ") for command in started.values()), f"no watchdog to check: {started}"
        process.send_signal(number)
        output, _ = process.communicate(timeout=120)
        assert process.returncode == status and "Stopped after" not in output
        deadline = time.monotonic() + 30
        while _still_running(started) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _still_running(started)
    finally:
        for pid in _still_running(started):
            os.kill(pid, signal.SIGKILL)
        process.kill()
        process.wait()


def test_a_timeout_that_isnt_a_number_is_refused(repo):
    done = repo.sh("size", env={**repo.env, "OCCAM_TIMEOUT": "abc"})
    assert done.returncode == 2 and "OCCAM_TIMEOUT" in done.stdout


def test_a_config_that_hides_everything_says_so(repo):
    repo.write(".occam.json", '{"ignore": ["*"]}')
    output = repo.sh("grep", "total").stdout
    assert output.startswith("0 matching") and "leaves out: *" in output


def test_leaks_doesnt_claim_a_setting_left_out_what_it_read(repo):
    repo.write(".occam.json", '{"ignore": ["secrets"]}')
    repo.write("secrets/conf.py", f'KEY = "{TOKEN}"\n')
    repo.write("secrets/other.py", f'KEY = "{TOKEN}"\n')
    repo.commit("one commit, two files")
    output = repo.sh("leaks").stdout
    assert "secrets/conf.py" in output and "leaves out" not in output and "credential-shaped lines: 2." in output


def test_a_bad_expression_is_an_error_in_a_plain_folder_too(plain):
    done = plain.sh("grep", "(")
    assert done.returncode == 2 and "Nothing was checked" in done.stdout


def test_naming_an_ignored_file_searches_it(repo):
    repo.write("ignored.py", "needle = 1\n")
    assert repo.sh("grep", "needle").stdout.startswith("0 matching")
    assert repo.sh("grep", "needle", "ignored.py").stdout.startswith("1 matching")


def test_options_need_values_and_leading_zeros_are_fine(repo):
    assert repo.sh("size", "--top").returncode == 2
    done = repo.sh("size", "--top", "08")
    assert done.returncode == 0 and "Raise --top" in done.stdout


def test_a_zsh_file_with_no_shebang_is_left_alone(repo):
    repo.write("a.zsh", "foo() { ) }\n")
    assert repo.sh("shell").returncode == 0


# ---------------------------------------------------------------- markers, tests, commands, entry

def test_markers_find_each_kind(repo):
    repo.write("x.sh", "#!/bin/sh\nset -e\nfoo || true\n")
    repo.write("ci.yml", "continue-on-error: true\n")
    output = repo.sh("markers", "--top", "100").stdout
    assert "suppression: 1 in 1 files" in output and "skipped-test: 1 in 1 files" in output
    assert "focused-test: 1 in 1 files" in output and "hidden-check: 2 in 2 files" in output


def test_markers_stay_out_of_documents(repo):
    repo.write("docs/guide.md", "Use `# noqa` and `|| true`.\n")
    assert "suppression: 1 in 1 files" in repo.sh("markers").stdout


def test_tests_lists_and_narrows(repo):
    assert repo.sh("tests").stdout.startswith("3 test files")
    output = repo.sh("tests", "app/core.py").stdout
    assert "tests/test_core.py" in output and "tests/test_skip.py" not in output
    assert "No test names this" in repo.sh("tests", "app/no_newline.py").stdout


def test_tests_counts_a_test_named_after_the_file(repo):
    repo.write("tests/test_lonely.py", "def test_a():\n    assert 1\n")
    repo.write("app/lonely.py", "x = 1\n")
    assert "tests/test_lonely.py" in repo.sh("tests", "app/lonely.py").stdout


def test_commands_lists_what_the_repository_states_and_runs_nothing(repo):
    marker = repo.path / "ran"
    repo.write("Makefile", f"build:\n\ttouch {marker}\n")
    output = repo.sh("commands", "--top", "100").stdout
    for expected in ("make build", '"lint": "eslint ."', "ruff check .", "pytest -q", "echo done", "pytest (inferred"):
        assert expected in output, expected
    assert not marker.exists()


def test_commands_agree_with_occam_py_on_ci_steps(repo):
    from_py = {row["command"] for rows in repo.py("commands", "--top", "100")["kinds"].values() for row in rows if row["how"] == "CI step"}
    output = repo.sh("commands", "--top", "100").stdout
    assert from_py == {"ruff check .", "pytest -q", "echo done"} and all(command in output for command in from_py)


def test_entry_finds_mains_routes_and_containers_and_leaves_tests_out(repo):
    repo.write("tests/test_routes.py", '@app.get("/in-a-test")\ndef t():\n    pass\n')
    output = repo.sh("entry", "--top", "100").stdout
    assert "app/core.py:5" in output and "app/api.py:4" in output and "Dockerfile:2" in output
    assert "in-a-test" not in output


# ---------------------------------------------------------------- shell

def test_shell_reports_a_script_that_doesnt_parse_and_exits_1(repo):
    repo.write("broken.sh", "#!/bin/bash\nif true; then\n")
    done = repo.sh("shell", "--top", "100")
    assert done.returncode == 1 and "broken.sh" in done.stdout and "Do not parse" in done.stdout


def test_shell_passes_clean_scripts_and_finds_common_defects(repo):
    done = repo.sh("shell", "--top", "100")
    assert done.returncode == 0
    assert "2 shell scripts. 0 fail to parse" in done.stdout
    assert "scripts/deploy.sh:2" in done.stdout.partition("could be empty")[2]
    assert "scripts/deploy.sh:3" in done.stdout.partition("output of ls")[2]
    assert "scripts/deploy.sh" in done.stdout.partition("Keep going")[2]


def test_shell_runs_nothing_it_checks(repo, tmp_path):
    marker = tmp_path / "ran"
    repo.write("evil.sh", f"#!/bin/bash\ntouch {marker}\n$(touch {marker})\n")
    done = repo.sh("shell")
    assert done.returncode == 0 and "Do not parse" not in done.stdout
    assert not marker.exists()


def test_script_never_uses_command_for_something_that_can_fail():
    """bash 3.2's `set -e` stops on a failing `command x` even inside `||`, which broke every search that found nothing."""
    assert not re.search(r"^\s*(?!#).*\bcommand (?!-v)\w", "\n".join(line for line in SOURCE.split("\n") if not line.lstrip().startswith("#")), re.M)


def test_shell_leaves_other_shells_alone(repo):
    repo.write("a.zsh", '#!/usr/bin/env zsh\nfoo() { ) }\n')
    assert repo.sh("shell").returncode == 0


def test_shell_with_no_scripts_says_so(tmp_path, bash):
    (tmp_path / "e").mkdir()
    repo = Repo(tmp_path / "e", tmp_path / "s", bash)
    repo.write("a.py", "x = 1\n")
    repo.git("init", "-q")
    assert repo.sh("shell").stdout.startswith("No shell scripts")


# ---------------------------------------------------------------- errors and hostile repositories

def test_help_and_unknown_commands(repo):
    assert "occam.sh: queries" in repo.sh().stdout and repo.sh().returncode == 0
    done = repo.sh("scan")
    assert done.returncode == 2 and "occam.py" in done.stdout


def test_doesnt_pass_writing_commands_through_to_occam_py(repo):
    for command in ("fix", "golden", "mutate", "bench", "goal"):
        assert repo.sh(command, "--apply").returncode == 2


def test_a_missing_path_and_a_bad_option_exit_2(repo, tmp_path):
    assert repo.sh("size", "nowhere").returncode == 2 and "No such path" in repo.sh("size", "nowhere").stdout
    assert repo.sh("size", str(tmp_path)).returncode == 2 and "outside this project" in repo.sh("size", str(tmp_path)).stdout
    assert repo.sh("size", "--nope").returncode == 2
    assert repo.sh("size", "--top", "many").returncode == 2
    assert repo.sh("find").returncode == 2


ALL_COMMANDS = (("size",), ("find", "total"), ("grep", "total"), ("history",), ("history", "app/core.py"), ("leaks",), ("markers",), ("tests",), ("tests", "app/core.py"), ("commands",), ("entry",), ("shell",), ("doctor",))


def _hostile(repo: Repo, marker: Path) -> None:
    payload = repo.path / ".git" / "payload.sh"
    payload.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    payload.chmod(0o755)
    for key, value in (("core.fsmonitor", payload), ("core.pager", payload), ("core.sshCommand", payload), ("diff.external", payload), ("filter.x.clean", payload),
                       ("filter.x.smudge", payload), ("diff.x.textconv", payload), ("gpg.program", payload), ("core.hooksPath", payload.parent), ("filter.we=ird.clean", payload)):
        repo.git("config", key, str(value))
    repo.write(".gitattributes", "* filter=x diff=x\n")


@pytest.mark.parametrize("args", ALL_COMMANDS, ids=lambda args: " ".join(args))
def test_nothing_runs_what_a_hostile_repository_names(tmp_path, bash, args):
    repo = make_repo(tmp_path / "r", tmp_path / "s", bash)
    marker = tmp_path / "ran"
    _hostile(repo, marker)
    assert repo.sh(*args).returncode == 0
    assert not marker.exists(), f"{args} ran something"


def _control_that_the_payload_works(repo: Repo, marker: Path) -> None:
    subprocess.run([GIT, "status"], cwd=repo.path, env=repo.env, capture_output=True)
    assert marker.exists(), "bare git didn't run the payload, so the hostile tests prove nothing here"


def test_the_hostile_payload_really_runs_under_bare_git(tmp_path, bash):
    repo = make_repo(tmp_path / "r", tmp_path / "s", bash)
    marker = tmp_path / "ran"
    _hostile(repo, marker)
    _control_that_the_payload_works(repo, marker)


@pytest.mark.parametrize("args", ALL_COMMANDS, ids=lambda args: " ".join(args))
def test_nothing_writes_to_the_repository(tmp_path, bash, args):
    repo = make_repo(tmp_path / "r", tmp_path / "s", bash)
    snapshot = lambda: sorted((str(p), p.stat().st_mtime_ns) for p in repo.path.rglob("*") if ".git" not in p.parts)  # noqa: E731
    before = snapshot()
    repo.sh(*args)
    assert before == snapshot()


def test_leaves_no_temporary_files_behind(tmp_path, bash):
    repo = make_repo(tmp_path / "r", tmp_path / "s", bash)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    repo.sh("size", env={**repo.env, "TMPDIR": str(scratch)})
    assert list(scratch.iterdir()) == []


def test_git_too_old_to_blank_drivers_means_treating_it_as_a_plain_folder(tmp_path, bash):
    repo = make_repo(tmp_path / "r", tmp_path / "s", bash)
    marker = tmp_path / "ran"
    _hostile(repo, marker)
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "git").write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version 2.30.1"; exit 0; fi\nexec {GIT} "$@"\n')
    (shim / "git").chmod(0o755)
    env = {**repo.env, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}
    assert repo.sh("history", env=env).returncode == 2
    assert repo.sh("size", env=env).returncode == 0
    assert not marker.exists()


def test_old_git_is_fine_when_the_repository_names_no_drivers(repo, tmp_path):
    """The host's own git config is left out: with git-lfs installed it names a filter, as on GitHub's runners, and old git can't blank that one either."""
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "git").write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version 2.30.1"; exit 0; fi\nexec {GIT} "$@"\n')
    (shim / "git").chmod(0o755)
    env = {**repo.env, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    assert repo.sh("history", env=env).returncode == 0


def test_works_with_no_python_on_the_host(repo, tmp_path, bash):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("awk", "sed", "grep", "wc", "sort", "tr", "cut", "find", "xargs", "dirname", "basename", "mktemp", "rm", "cp", "cat", "env", "git", "bash"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    env = {**repo.env, "PATH": str(bin_dir)}
    for args in ALL_COMMANDS:
        assert repo.sh(*args, env=env).returncode == 0, args
    assert "python3: missing" in repo.sh("doctor", env=env).stdout


def test_works_with_no_git_on_the_host(plain, tmp_path, bash):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("awk", "sed", "grep", "wc", "sort", "tr", "cut", "find", "xargs", "dirname", "basename", "mktemp", "rm", "cp", "cat", "env", "bash"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    env = {**plain.env, "PATH": str(bin_dir)}
    assert plain.sh("size", env=env).returncode == 0
    assert plain.sh("find", "total", env=env).returncode == 0
    assert plain.sh("history", env=env).returncode == 2
    assert "git: missing" in plain.sh("doctor", env=env).stdout
