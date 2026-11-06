"""occam.sh, run for real under each bash here, and compared with occam.py on the same repositories."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugin" / "skills" / "occam" / "scripts"
TOOL = SCRIPTS / "occam.sh"
OCCAM = SCRIPTS / "occam.py"
GIT = shutil.which("git")
TOKEN = "ghp_" + "a1B2" * 10
sys.path.insert(0, str(SCRIPTS))

from occam_tools import files as filesystem, source  # noqa: E402

BASHES = sorted({found for found in (shutil.which("bash"), "/bin/bash" if os.path.exists("/bin/bash") else None) if found})
SOURCE = TOOL.read_text()

FILES = {
    ".gitignore": "__pycache__/\nignored.py\n",
    ".occam.json": '{\n  "ignore": ["fixtures", "*.skipme.py"]\n}\n',
    "pyproject.toml": '[project]\nname = "demo"\n\n[tool.pytest.ini_options]\n\n[tool.ruff]\nline-length = 100\n',
    "Makefile": "build:\n\tpython -m build\n\ntest:\n\tpytest -q\n\n.PHONY: build\n",
    "package.json": '{\n  "name": "x",\n  "scripts": {\n    "lint": "eslint ."\n  }\n}\n',
    "Dockerfile": 'FROM python:3\nCMD ["python", "tool.py"]\n',
    ".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - run: ruff check .\n      - run: |\n          pytest -q\n          echo done\n",
    "README.md": "total appears here\n",
    "app/core.py": 'def total(a):\n    return a\n\n\nif __name__ == "__main__":\n    print(total(1))\n',
    "app/api.py": 'from app.core import total\n\n\n@app.get("/health")\ndef health():\n    return total(1)  # noqa: E501\n',
    "app/no_newline.py": "x = 1",
    "app/spaced name.py": "y = 2\ntotal = 3\n",
    "app/-dash.py": "z = 3\n",
    "app/ünicode.py": "total = 4\n",
    "tests/test_core.py": "from app.core import total\n\n\ndef test_total():\n    assert total(1) == 1\n",
    "tests/test_skip.py": "import pytest\n\n\n@pytest.mark.skip\ndef test_a():\n    assert 1\n",
    "web/app.test.js": "it.only('x', () => {})\n",
    "fixtures/skipped.py": "total = 5\n",
    "a.skipme.py": "total = 6\n",
    "vendor/lib.py": "total = 7\n",
    "dist/out.min.js": "total = 8\n",
    "go.sum": "x\n",
    "bin/run": "#!/usr/bin/env bash\nset -e\necho hi\n",
    "bin/data": "not a script\n",
    "scripts/deploy.sh": '#!/bin/sh\nrm -rf "$dir"/*\nfor f in $(ls); do echo "$f"; done\n',
}


class Repo:
    def __init__(self, path: Path, state: Path, bash: str) -> None:
        self.path, self.bash = path, bash
        self.env = {**os.environ, "OCCAM_STATE_DIR": str(state), "GIT_AUTHOR_NAME": "Ann", "GIT_AUTHOR_EMAIL": "a@example.invalid",
                    "GIT_COMMITTER_NAME": "Ann", "GIT_COMMITTER_EMAIL": "a@example.invalid", "PYTHONDONTWRITEBYTECODE": "1"}

    def write(self, name: str, content: str) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def git(self, *args: str, author: str = "Ann") -> str:
        return subprocess.run([GIT, *args], cwd=self.path, env={**self.env, "GIT_AUTHOR_NAME": author}, capture_output=True, text=True, check=True).stdout

    def commit(self, message: str = "c", author: str = "Ann") -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message, author=author)

    def sh(self, *args: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([self.bash, str(TOOL), *args], cwd=cwd or self.path, env=env or self.env, capture_output=True, text=True, timeout=120)

    def py(self, *args: str) -> dict:
        done = subprocess.run([sys.executable, str(OCCAM), "query", *args, "--format", "json"], cwd=self.path, env=self.env, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stdout + done.stderr
        return json.loads(done.stdout)


def make_repo(path: Path, state: Path, bash: str, git: bool = True) -> Repo:
    path.mkdir()
    repo = Repo(path, state, bash)
    for name, content in FILES.items():
        repo.write(name, content)
    if git:
        repo.git("init", "-q")
        repo.commit("init")
    return repo


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


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck isn't installed")
def test_shellcheck_passes():
    done = subprocess.run(["shellcheck", "--severity=warning", str(TOOL)], capture_output=True, text=True)
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
    assert "app/conf.py" in output and TOKEN not in output and "1 commits added" in output


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
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "git").write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version 2.30.1"; exit 0; fi\nexec {GIT} "$@"\n')
    (shim / "git").chmod(0o755)
    assert repo.sh("history", env={**repo.env, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}).returncode == 0


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
