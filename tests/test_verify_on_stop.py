"""The hook's protocol, run as a real subprocess the way both hosts run it."""

import contextlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "adapters" / "hooks" / "verify_on_stop.py"
TOOLS = ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam_tools" / "files.py"
PY = sys.executable
GIT = "/Library/Developer/CommandLineTools/usr/bin/git" if Path("/Library/Developer/CommandLineTools/usr/bin/git").exists() else shutil.which("git")


def run_hook(event, *argv, cwd=None):
    payload = event if isinstance(event, str) else json.dumps(event)
    return subprocess.run([PY, str(HOOK), *argv], input=payload, capture_output=True, text=True, cwd=cwd, timeout=30)


@pytest.fixture
def dirty_repo(tmp_path):
    subprocess.run([GIT, "init", "-q", "."], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("changed\n")
    return tmp_path


@pytest.fixture
def clean_repo(tmp_path):
    subprocess.run([GIT, "init", "-q", "."], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("x\n")
    subprocess.run([GIT, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([GIT, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    return tmp_path


def reason(done):
    """The hook blocks with JSON on stdout and exit 0, which is the form both hosts document."""
    assert done.returncode == 0, done.stderr
    decision = json.loads(done.stdout)
    assert decision["decision"] == "block"
    return decision["reason"]


def test_passing_check_exits_zero_with_empty_stdout(dirty_repo):
    """Codex rejects plain text on stdout for a Stop hook that exits 0, so stdout must stay empty."""
    done = run_hook({"cwd": str(dirty_repo)}, "--", PY, "-c", "print('noise on stdout')")
    assert done.returncode == 0
    assert done.stdout == ""


def test_failing_check_blocks_with_reason(dirty_repo):
    text = reason(run_hook({"cwd": str(dirty_repo)}, "--", PY, "-c", "print('E101 bad'); raise SystemExit(3)"))
    assert "exit code 3" in text
    assert "E101 bad" in text
    assert "authorizes no edits" in text


def test_failure_mentioning_a_missing_file_still_blocks(dirty_repo):
    """Claude Code treats exit 2 with this on stderr as non-blocking, which is why the hook uses JSON."""
    code = "import sys; print('No such file or directory', file=sys.stderr); raise SystemExit(1)"
    assert "exit code 1" in reason(run_hook({"cwd": str(dirty_repo)}, "--", PY, "-c", code))


def test_loop_guard_lets_the_agent_finish(dirty_repo):
    done = run_hook({"cwd": str(dirty_repo), "stop_hook_active": True}, "--", PY, "-c", "raise SystemExit(1)")
    assert done.returncode == 0
    assert done.stdout == ""


def test_clean_tree_skips_the_check(clean_repo):
    marker = clean_repo / "ran"
    done = run_hook({"cwd": str(clean_repo)}, "--", PY, "-c", f"open({str(marker)!r},'w')")
    assert done.returncode == 0
    assert not marker.exists()


def test_outside_a_repository_the_check_still_runs(tmp_path):
    assert "exit code 1" in reason(run_hook({"cwd": str(tmp_path)}, "--", PY, "-c", "raise SystemExit(1)"))


def test_runs_from_the_repository_root_when_cwd_moved(dirty_repo):
    (dirty_repo / "sub").mkdir()
    code = "import os,sys; sys.exit(0 if os.path.exists('file.txt') else 1)"
    done = run_hook({"cwd": str(dirty_repo / "sub")}, "--", PY, "-c", code)
    assert done.stdout == ""


def test_relative_script_resolves_against_the_repository(dirty_repo):
    script = dirty_repo / "check.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    done = run_hook({"cwd": str(dirty_repo)}, "--", "./check.sh")
    assert done.stdout == "", done.stdout


def test_missing_tool_is_reported_as_not_run_rather_than_passing(dirty_repo):
    assert "not run" in reason(run_hook({"cwd": str(dirty_repo)}, "--", "definitely-not-a-real-tool-xyz"))


def test_deleted_working_directory_is_reported_as_not_run(tmp_path):
    gone = tmp_path / "gone"
    assert "not run" in reason(run_hook({"cwd": str(gone)}, "--", PY, "-c", "raise SystemExit(0)"))


def test_undecodable_output_does_not_let_a_failure_through(dirty_repo):
    code = "import sys; sys.stdout.buffer.write(b'\\xff\\xfe bad bytes'); raise SystemExit(1)"
    assert "exit code 1" in reason(run_hook({"cwd": str(dirty_repo)}, "--", PY, "-c", code))


def test_timeout_is_reported_as_not_completed(dirty_repo):
    done = run_hook({"cwd": str(dirty_repo)}, "--timeout", "0.5", "--", PY, "-c", "import time; time.sleep(20)")
    assert "not completed" in reason(done)


def test_no_shell_interpolation(dirty_repo):
    pwned = dirty_repo / "pwned"
    code = "import sys; raise SystemExit(0 if sys.argv[1] == '$(touch pwned)' else 9)"
    done = run_hook({"cwd": str(dirty_repo)}, "--", PY, "-c", code, "$(touch pwned)")
    assert done.stdout == "", done.stdout
    assert not pwned.exists()


def test_secrets_redacted_from_reason(dirty_repo):
    code = "print('API_KEY=abc123 token: zzz999'); raise SystemExit(1)"
    text = reason(run_hook({"cwd": str(dirty_repo)}, "--", PY, "-c", code))
    assert "abc123" not in text and "zzz999" not in text
    assert "[redacted]" in text


@pytest.mark.parametrize("stdin", ["not json", "[1,2]", ""])
def test_malformed_event_does_not_crash(stdin, dirty_repo):
    done = run_hook(stdin, "--", PY, "-c", "raise SystemExit(0)", cwd=dirty_repo)
    assert done.returncode == 0


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="no system python")
def test_runs_on_the_stock_system_python(dirty_repo):
    payload = json.dumps({"cwd": str(dirty_repo)})
    done = subprocess.run(["/usr/bin/python3", str(HOOK), "--", PY, "-c", "raise SystemExit(1)"], input=payload,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["decision"] == "block"


# What a repository delivered with its .git folder can name for git status to run.


def _program(repo, marker):
    script = repo.parent / "program.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    script.chmod(0o755)
    return script


def _commit(repo):
    subprocess.run([GIT, "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run([GIT, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "x"], cwd=repo, check=True, capture_output=True)


def _fsmonitor(repo, marker):
    subprocess.run([GIT, "config", "core.fsmonitor", str(_program(repo, marker))], cwd=repo, check=True)


def _clean_filter(repo, marker):
    (repo / ".gitattributes").write_text("*.txt filter=named\n")
    subprocess.run([GIT, "config", "filter.named.clean", f"touch '{marker}'; cat"], cwd=repo, check=True)


def _index_hook(repo, marker):
    shutil.copy(_program(repo, marker), repo / ".git" / "hooks" / "post-index-change")


def _submodule_fsmonitor(repo, marker):
    inner = repo / "sub"
    inner.mkdir()
    subprocess.run([GIT, "init", "-q", "."], cwd=inner, check=True)
    (inner / "inner.txt").write_text("x\n")
    _commit(inner)
    _commit(repo)
    (inner / "inner.txt").write_text("changed\n")
    subprocess.run([GIT, "config", "core.fsmonitor", str(_program(repo, marker))], cwd=inner, check=True)


def _unnamed_filter(repo, marker):
    (repo / ".gitattributes").write_text("*.txt filter=\n")
    with open(repo / ".git" / "config", "a") as config:
        config.write(f"[filter \"\"]\n\tclean = touch '{marker}'; cat\n")


def _non_utf8_filter(repo, marker):
    (repo / ".gitattributes").write_bytes(b"*.txt filter=\xff\n")
    with open(repo / ".git" / "config", "ab") as config:
        config.write(b"[filter \"\xff\"]\n\tclean = touch '" + os.fsencode(marker) + b"'; cat\n")


def _submodule_entry(repo, marker):
    """The entry outranks -c diff.ignoreSubmodules, and the submodule's own filter never shows in the outer config."""
    inner = repo / "sub"
    inner.mkdir()
    subprocess.run([GIT, "init", "-q", "."], cwd=inner, check=True)
    (inner / ".gitattributes").write_text("*.txt filter=named\n")
    (inner / "inner.txt").write_text("x\n")
    _commit(inner)
    (repo / ".gitmodules").write_text('[submodule "sub"]\n\tpath = sub\n\turl = ./sub\n\tignore = none\n')
    _commit(repo)
    subprocess.run([GIT, "config", "filter.named.clean", f"touch '{marker}'; cat"], cwd=inner, check=True)
    (inner / "inner.txt").write_text("y\n")  # the same size, or git sees the change without running the filter


def _missing_objects(repo, **settings):
    """Reading a tree this clone lacks makes git fetch it, from wherever the config says."""
    tree = subprocess.run([GIT, "rev-parse", "HEAD^{tree}"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    (repo / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
    (repo / ".git" / "index").unlink()
    for key, value in {"core.repositoryformatversion": "1", "extensions.partialClone": "origin", "remote.origin.promisor": "true", **settings}.items():
        subprocess.run([GIT, "config", key, value], cwd=repo, check=True)


def _ext_fetch(repo, marker):
    _missing_objects(repo, **{"remote.origin.url": f"ext::sh -c touch% {marker}", "protocol.ext.allow": "always"})


def _file_fetch(repo, marker):
    _missing_objects(repo, **{"remote.origin.url": str(repo), "remote.origin.uploadpack": f"touch '{marker}'; false #", "protocol.file.allow": "always"})


def _helper_fetch(repo, marker):
    _missing_objects(repo, **{"remote.origin.url": "none::x", "alias.remote-none": f"!touch '{marker}'"})


@pytest.mark.parametrize("name_a_program", [_fsmonitor, _clean_filter, _index_hook, _submodule_fsmonitor, _unnamed_filter, _non_utf8_filter,
                                            _submodule_entry, _ext_fetch, _file_fetch, _helper_fetch])
def test_git_status_runs_no_program_the_repository_names(name_a_program, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "program-ran"
    subprocess.run([GIT, "init", "-q", "."], cwd=repo, check=True)
    (repo / "file.txt").write_text("x\n")
    (repo / "same.txt").write_text("x\n")
    _commit(repo)
    name_a_program(repo, marker)
    (repo / "file.txt").write_text("changed\n")
    os.utime(repo / "same.txt", (2_000_000_000, 2_000_000_000))  # so a status would refresh the index
    # Plain git has to run it, on a copy so this leaves the repository as it was, or the test proves nothing.
    copy = tmp_path / "copy"
    shutil.copytree(repo, copy, symlinks=True)
    subprocess.run([GIT, "status", "--porcelain"], cwd=copy, capture_output=True)
    if not marker.exists():
        pytest.skip("this git doesn't run it, so there is nothing to block")
    marker.unlink()
    text = reason(run_hook({"cwd": str(repo)}, "--", PY, "-c", "raise SystemExit(3)"))
    assert "exit code 3" in text, "the change has to still count, so the check runs"
    assert not marker.exists(), "through the adapter"
    tools = runpy.run_path(str(TOOLS))
    for ask in (tools["dirty_paths"], tools["changed_lines"], tools["removed_and_renamed"], tools["submodule_paths"]):
        with contextlib.suppress(tools["GitProblem"]):  # a repository missing objects can't answer, and that's fine
            ask(repo)
    assert not marker.exists(), "through the shared wrapper"


def test_repository_config_cant_hide_a_change_from_the_check(clean_repo):
    subprocess.run([GIT, "config", "status.showUntrackedFiles", "no"], cwd=clean_repo, check=True)
    (clean_repo / "new.txt").write_text("new\n")
    assert "exit code 3" in reason(run_hook({"cwd": str(clean_repo)}, "--", PY, "-c", "raise SystemExit(3)"))


def test_the_plugin_only_calls_git_through_the_wrapper():
    """A plain git call is how a repository's config got to run programs, so a new one should have to explain itself."""
    plain = [str(path) for path in (ROOT / "plugin").rglob("*.py") if re.search(r"""\[\s*["']git["']""", path.read_text(encoding="utf-8"))]
    assert not plain


def test_git_safety_stays_in_step_with_the_tools():
    """This script is copied on its own, so it can't import the list. A route closed there has to be closed here too."""
    tools = runpy.run_path(str(ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam_tools" / "files.py"))
    here = runpy.run_path(str(HOOK))
    assert here["GIT_SAFETY"] == tools["_GIT_SAFETY"]
    assert here["GIT_ENVIRONMENT"] == tools["_GIT_ENVIRONMENT"]
    assert here["DRIVER_KEY"] == tools["_DRIVER_KEY"]


def _committed_repo(tmp_path, name="repo"):
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", "."], cwd=repo, check=True)
    (repo / "file.txt").write_text("x\n")
    _commit(repo)
    return repo


def test_the_one_protocol_allowed_cant_be_named_by_a_repository(tmp_path):
    """The variable lists protocols to allow, so its value has to be a name no helper can have. `none` could: alias.remote-none."""
    value = runpy.run_path(str(TOOLS))["_GIT_ENVIRONMENT"]["GIT_ALLOW_PROTOCOL"]
    repo = _committed_repo(tmp_path)
    assert subprocess.run([GIT, "config", f"alias.remote-{value}", "!touch x"], cwd=repo, capture_output=True).returncode != 0
    (repo / ".git" / "config").open("a").write(f"[alias]\n\tremote-{value} = !touch x\n")
    assert subprocess.run([GIT, "status"], cwd=repo, capture_output=True).returncode != 0, "a hand-written entry has to be a bad config"


def test_a_submodule_diff_runs_no_program_its_config_names(tmp_path):
    """diff.submodule=diff asks git to diff inside the submodule, under the submodule's own config."""
    repo = _committed_repo(tmp_path)
    marker = tmp_path / "program-ran"
    inner = repo / "sub"
    inner.mkdir()
    subprocess.run([GIT, "init", "-q", "."], cwd=inner, check=True)
    (inner / ".gitattributes").write_text("*.txt diff=named\n")
    (inner / "inner.txt").write_text("x\n")
    _commit(inner)
    _commit(repo)
    (inner / "inner.txt").write_text("y\n")
    _commit(inner)  # the outer repository now sees a moved commit
    subprocess.run([GIT, "config", "diff.submodule", "diff"], cwd=repo, check=True)
    subprocess.run([GIT, "config", "diff.named.command", f"touch '{marker}'; true"], cwd=inner, check=True)
    subprocess.run([GIT, "diff"], cwd=repo, capture_output=True)
    if not marker.exists():
        pytest.skip("this git doesn't run it, so there is nothing to block")
    marker.unlink()
    runpy.run_path(str(TOOLS))["changed_lines"](repo)
    assert not marker.exists()


def test_settings_passed_through_the_environment_still_apply(tmp_path, monkeypatch):
    """Blanking drivers uses the same variables, so it has to add to what's there, not replace it."""
    repo = _committed_repo(tmp_path)
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    if subprocess.run([GIT, "rev-parse", "--git-dir"], cwd=repo, capture_output=True).returncode == 0:
        pytest.skip("this git doesn't honor the ownership test setting")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.directory")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "*")
    assert subprocess.run([GIT, "rev-parse", "--git-dir"], cwd=repo, capture_output=True).returncode == 0
    assert runpy.run_path(str(TOOLS))["run_git"](repo, "rev-parse", "--git-dir") is not None
    assert run_hook({"cwd": str(repo)}, "--", PY, "-c", "raise SystemExit(3)").stdout == "", "a clean tree skips the check"


def test_git_config_in_the_environment_doesnt_hide_the_repository_drivers(tmp_path, monkeypatch):
    repo = _committed_repo(tmp_path)
    marker = tmp_path / "program-ran"
    _clean_filter(repo, marker)
    (repo / "file.txt").write_text("y\n")  # the same size, or git sees the change without running the filter
    empty = tmp_path / "empty-config"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG", str(empty))
    assert "exit code 3" in reason(run_hook({"cwd": str(repo)}, "--", PY, "-c", "raise SystemExit(3)"))
    runpy.run_path(str(TOOLS))["run_git"](repo, "status", "--porcelain")
    assert not marker.exists()


def test_git_config_that_cant_be_read_means_no_answer_rather_than_drivers_left_on(tmp_path, monkeypatch):
    """A setting in the environment can make listing die. The adapter then runs the check, and the wrapper says it can't tell."""
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "program-ran"
    subprocess.run([GIT, "init", "-q", "."], cwd=repo, check=True)
    (repo / "file.txt").write_text("x\n")
    _commit(repo)
    _clean_filter(repo, marker)
    (repo / "file.txt").write_text("y\n")  # the same size, or git sees the change without running the filter
    env = {**os.environ, "GIT_CONFIG_COUNT": "abc"}
    done = subprocess.run([PY, str(HOOK), "--", PY, "-c", "raise SystemExit(3)"], input=json.dumps({"cwd": str(repo)}), capture_output=True, text=True, env=env, timeout=30)
    assert "exit code 3" in reason(done)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "abc")
    assert runpy.run_path(str(TOOLS))["run_git"](repo, "status", "--porcelain") is None
    assert not marker.exists()
