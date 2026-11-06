"""The occam command line, run for real against real git repositories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OCCAM = ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam.py"
GIT = shutil.which("git")


class Repo:
    def __init__(self, path: Path, state: Path) -> None:
        self.path = path
        self.env = {**os.environ, "OCCAM_STATE_DIR": str(state), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "PYTHONDONTWRITEBYTECODE": "1"}

    def write(self, name: str, content: str) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def git(self, *args: str) -> str:
        return subprocess.run([GIT, *args], cwd=self.path, env=self.env, capture_output=True, text=True, check=True).stdout

    def commit(self, message: str = "c") -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def occam(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(OCCAM), *args], cwd=self.path, env=self.env, capture_output=True, text=True, input=stdin, timeout=120)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    made = Repo(path, tmp_path / "state")
    made.git("init", "-q")
    made.write(".gitignore", "__pycache__/\n.pytest_cache/\n")
    made.write("app/__init__.py", "")
    made.write("app/core.py", "def total(a, b):\n    if a > 0 and b > 0:\n        return a + b\n    return 0\n")
    made.write("tests/__init__.py", "")
    made.write("tests/test_core.py", "from app.core import total\n\n\ndef test_total():\n    assert total(1, 2) == 3\n    assert total(-1, 2) == 0\n")
    made.commit("init")
    return made


def test_map_describes_the_repository(repo):
    done = repo.occam("map")
    assert done.returncode == 0
    assert "file:" in done.stdout or "small repository" in done.stdout or "cell" in done.stdout
    assert "Strategy:" in done.stdout and "Agents:" in done.stdout and "Layers" in done.stdout
    data = json.loads(repo.occam("map", "--format", "json").stdout)
    assert data["test_files"] >= 1 and data["agents"]["readers_for_audit"] == 0
    assert any(row["layer"] == "hardware" for row in data["layers"])


def test_map_shows_the_worst_leads_it_already_found(repo):
    repo.write("bad.py", "import subprocess\n\ndef run(name):\n    subprocess.run(f'ls {name}', shell=True)\n")
    done = repo.occam("map")
    assert done.returncode == 0
    head = done.stdout.split("Tests:", 1)[0]  # above the rest, so `map | head` still shows it
    assert "shell-injection  bad.py:4" in head and "unconfirmed" in head
    data = json.loads(repo.occam("map", "--format", "json").stdout)
    assert data["lead_count"] >= len(data["leads"]) >= 1


def test_map_sees_ai_attribution_and_other_activity(repo):
    repo.write("x.py", "x = 1\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "work\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    repo.write("y.py", "y = 1\n")
    data = json.loads(repo.occam("map", "--format", "json").stdout)
    assert data["ai_commits"]["ai_attributed"] == 1
    assert data["activity"]["dirty_files"] == 1


def test_scan_output_is_bounded_and_saves_everything(repo):
    repo.write("app/many.py", "".join(f"def f{i}(x=[]):\n    return x\n" for i in range(200)))
    done = repo.occam("scan", "--top", "5")
    assert "... and" in done.stdout and "Full results:" in done.stdout
    assert len(done.stdout.splitlines()) < 60
    saved = json.loads(Path(done.stdout.split("Full results: ")[1].strip()).read_text())
    assert len([f for f in saved["findings"] if f["rule"] == "mutable-default"]) == 200


def test_scan_changed_only_sees_new_lines(repo):
    repo.write("app/core.py", "def old(x=[]):\n    return x\n")
    repo.commit()
    repo.write("app/core.py", "def old(x=[]):\n    return x\n\n\ndef added(y=[]):\n    return y\n")
    data = json.loads(repo.occam("scan", "--changed", "--format", "json").stdout)
    defaults = [f for f in data["findings"] if f["rule"] == "mutable-default"]
    assert [f["line"] for f in defaults] == [5]


def test_scan_stdin_handles_a_snippet(repo):
    done = repo.occam("scan", "--stdin", "--format", "json", stdin="import os\nprint(os.path.exist('x'))\n")
    rules = {f["rule"] for f in json.loads(done.stdout)["findings"]}
    assert "phantom-attribute" in rules


def test_sarif_is_valid_shape(repo):
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n")
    document = json.loads(repo.occam("scan", "--format", "sarif").stdout)
    assert document["version"] == "2.1.0"
    assert document["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"] >= 1


def test_fail_on_sets_the_exit_code(repo):
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n")
    assert repo.occam("scan", "--fail-on", "high").returncode == 1
    assert repo.occam("scan", "--fail-on", "critical").returncode == 0


def test_baseline_ratchets(repo):
    repo.write("app/old.py", "def f(x=[]):\n    return x\n")
    repo.commit()
    repo.occam("baseline", "write")
    assert "mutable-default" not in repo.occam("scan", "--new-only").stdout
    repo.write("app/new.py", "def g(y=[]):\n    return y\n")
    assert "mutable-default" in repo.occam("scan", "--new-only").stdout


def test_ledger_tracks_a_finding_to_fixed(repo):
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n")
    repo.commit()
    assert "new" in repo.occam("ledger", "sync").stdout
    batch = repo.occam("ledger", "next", "--owner", "a1", "--size", "1").stdout
    assert "a1" in batch and "app/bad.py" in batch
    identifier = batch.split("\n")[1].split()[0]
    assert "in-progress" in repo.occam("ledger", "list").stdout
    repo.write("app/bad.py", "def f(x=None):\n    return x\n")
    assert "1 no longer present" in repo.occam("ledger", "sync").stdout
    assert identifier in repo.occam("ledger", "list", "--status", "fixed").stdout


def test_ledger_next_never_hands_one_file_to_two_agents(repo):
    repo.write("app/bad.py", "def f(x=[]):\n    return x\n\n\ndef g(y=[]):\n    return y\n")
    repo.write("app/also.py", "def h(z=[]):\n    return z\n")
    repo.commit()
    repo.occam("ledger", "sync")
    first = repo.occam("ledger", "next", "--owner", "a1", "--size", "1", "--tier", "B").stdout.split("\n")[0]
    second = repo.occam("ledger", "next", "--owner", "a2", "--size", "1", "--tier", "B").stdout.split("\n")[0]
    assert first.split(" in ")[-1] != second.split(" in ")[-1]


def test_decisions_and_report(repo):
    repo.write("app/bad.py", "def verify_token(t):\n    return True\n")
    repo.commit()
    repo.occam("ledger", "sync")
    identifier = json.loads(repo.occam("scan", "--format", "json").stdout)["findings"][0]["id"]
    repo.occam("ledger", "set", "--ids", identifier, "--status", "needs-decision", "--note", "ask about rollout")
    decisions = repo.occam("ledger", "decisions").stdout
    assert "fake-success" in decisions and "ask about rollout" in decisions
    out = repo.path.parent / "AUDIT.md"
    repo.occam("ledger", "report", "--out", str(out))
    assert "fake-success" in out.read_text()


def test_fix_is_dry_by_default_and_proves_itself(repo):
    source = "import os\nimport json\n\n# Here's the updated function\ndef f():\n    return json.dumps({})\n"
    repo.write("app/x.py", source)
    repo.commit()
    dry = repo.occam("fix", "--rule", "unused-import")
    assert "Dry run" in dry.stdout and "-import os" in dry.stdout
    assert (repo.path / "app/x.py").read_text() == source
    assert repo.occam("fix", "--apply", "--rule", "unused-import", "--rule", "ai-residue").returncode == 0
    fixed = (repo.path / "app/x.py").read_text()
    assert "import os" not in fixed and "Here's" not in fixed and "import json" in fixed
    assert repo.git("status", "--porcelain").strip().endswith("app/x.py"), "nothing else was touched and nothing committed"


def test_fix_refuses_uncommitted_work(repo):
    repo.write("app/x.py", "import os\nprint(1)\n")
    repo.commit()
    repo.write("app/x.py", "import os\nprint(2)\n")
    done = repo.occam("fix", "--apply", "--rule", "unused-import")
    assert "uncommitted" in done.stdout
    assert "import os" in (repo.path / "app/x.py").read_text()
    assert repo.occam("fix", "--apply", "--allow-dirty", "--rule", "unused-import").returncode == 0
    assert "import os" not in (repo.path / "app/x.py").read_text()


def test_fix_respects_another_agents_claim(repo):
    repo.write("app/x.py", "import os\nprint(1)\n")
    repo.commit()
    repo.occam("coord", "claim", "app/x.py", "--owner", "other")
    assert "claimed by other" in repo.occam("fix", "--apply", "--rule", "unused-import").stdout
    assert "import os" in (repo.path / "app/x.py").read_text()
    assert repo.occam("fix", "--apply", "--owner", "other", "--rule", "unused-import").returncode == 0
    assert "import os" not in (repo.path / "app/x.py").read_text()


def test_fix_keeps_reexports_and_documented_imports(repo):
    repo.write("app/lib.py", "from os import sep\n")
    repo.write("app/user.py", "from app.lib import sep\nprint(sep)\n")
    repo.write("app/doc.py", "import os  # needed for its side effect\nprint(1)\n")
    repo.commit()
    repo.occam("fix", "--apply", "--rule", "unused-import")
    assert "from os import sep" in (repo.path / "app/lib.py").read_text()
    assert "import os" in (repo.path / "app/doc.py").read_text()


def test_fix_leaves_commented_out_code_unless_asked(repo):
    source = "x = 1\n# y = compute(x)\n# z = y + 1\n# print(z)\nw = 2\n"
    repo.write("app/x.py", source)
    repo.commit()
    repo.occam("fix", "--apply")
    assert (repo.path / "app/x.py").read_text() == source
    repo.occam("fix", "--apply", "--rule", "commented-out-code")
    assert (repo.path / "app/x.py").read_text() == "x = 1\nw = 2\n"


def test_fix_names_what_it_cant_do(repo):
    assert repo.occam("fix", "--rule", "sql-injection").returncode == 2


def test_golden_catches_a_behavior_change(repo):
    command = [sys.executable, "-c", "from app.core import total; print(total(1, 2))"]
    assert repo.occam("golden", "record", "t", "--", *command).returncode == 0
    assert repo.occam("golden", "check", "t").returncode == 0
    repo.write("app/core.py", "def total(a, b):\n    return a - b\n")
    done = repo.occam("golden", "check", "t")
    assert done.returncode == 1 and "CHANGED" in done.stdout


def test_golden_refuses_nondeterministic_commands(repo):
    command = [sys.executable, "-c", "import time; print(time.time())"]
    assert repo.occam("golden", "record", "t", "--", *command).returncode == 1
    assert repo.occam("golden", "record", "t", "--normalize", r"\d+\.\d+", "--", *command).returncode == 0


def test_mutate_finds_what_tests_miss_and_leaves_the_tree_alone(repo):
    before = (repo.path / "app/core.py").read_text()
    done = repo.occam("mutate", "--cmd", f"{sys.executable} -m pytest -q -p no:cacheprovider tests")
    assert (repo.path / "app/core.py").read_text() == before
    assert "deliberate breakages" in done.stdout
    assert done.returncode == 1 and "still pass" in done.stdout


def test_mutate_refuses_a_broken_baseline(repo):
    repo.write("tests/test_core.py", "def test_bad():\n    assert False\n")
    done = repo.occam("mutate", "--cmd", f"{sys.executable} -m pytest -q -p no:cacheprovider tests")
    assert done.returncode == 2 and "don't pass" in done.stdout


def test_bench_reports_growth_and_limits(repo):
    repo.write("q.py", "import sys\nn = int(sys.argv[1])\nprint(sum(1 for i in range(n) for j in range(n)))\n")
    done = repo.occam("bench", "--cmd", f"{sys.executable} q.py {{n}}", "--sizes", "1000,2000,4000", "--repeat", "1")
    assert "n^" in done.stdout and "quadratic" in done.stdout
    assert done.returncode == 1
    over = repo.occam("bench", "--cmd", f"{sys.executable} q.py {{n}}", "--sizes", "500,1000", "--repeat", "1", "--limit-seconds", "0.0001")
    assert "EXCEEDED" in over.stdout and over.returncode == 1


def test_bench_says_when_a_run_is_too_small_to_show_growth(repo):
    done = repo.occam("bench", "--cmd", f"{sys.executable} -c pass # {{n}}", "--sizes", "1,2", "--repeat", "1")
    assert "Not enough signal" in done.stdout


def test_coord_claims_are_exclusive_and_expire(repo):
    assert repo.occam("coord", "claim", "app/core.py", "--owner", "a").returncode == 0
    assert repo.occam("coord", "claim", "app/core.py", "--owner", "b").returncode == 1
    assert repo.occam("coord", "check", "app/core.py", "--owner", "b").returncode == 1
    assert repo.occam("coord", "release", "--owner", "a").returncode == 0
    assert repo.occam("coord", "claim", "app/core.py", "--owner", "b", "--ttl", "-1").returncode == 0
    assert repo.occam("coord", "claim", "app/core.py", "--owner", "c").returncode == 0, "an expired claim doesn't block"


def test_coord_status_shows_uncommitted_work(repo):
    repo.write("app/core.py", "x = 1\n")
    assert "app/core.py" in repo.occam("coord", "status").stdout


def test_goal_verify_is_the_gate(repo):
    assert repo.occam("goal", "status").returncode == 2
    repo.occam("goal", "init", "totals are correct")
    check = f"{sys.executable} -m pytest -q -p no:cacheprovider tests"
    repo.occam("goal", "add", "adds positives", "--check", check)
    assert "ALL VERIFIED" in repo.occam("goal", "verify").stdout
    repo.occam("goal", "add", "handles overflow")
    done = repo.occam("goal", "verify")
    assert done.returncode == 1 and "NOT DONE" in done.stdout


def test_goal_evidence_goes_stale_when_the_tree_changes(repo):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "add", "works", "--check", f"{sys.executable} -c pass")
    repo.occam("goal", "verify")
    assert "verified" in repo.occam("goal", "status").stdout
    repo.write("app/core.py", "x = 2\n")
    assert "stale" in repo.occam("goal", "status").stdout


def test_goal_zero_tests_isnt_verified(repo):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "add", "works", "--check", f"{sys.executable} -c \"print('collected 0 items')\"")
    assert repo.occam("goal", "verify").returncode == 1


def test_goal_constraints_and_scope_catch_drift(repo):
    repo.occam("goal", "init", "x")
    repo.occam("goal", "add", "works", "--check", f"{sys.executable} -c pass")
    repo.occam("goal", "constrain", "--forbid", "migrations/*")
    repo.occam("goal", "scope", "app/")
    repo.write("migrations/1.sql", "DROP TABLE t;\n")
    done = repo.occam("goal", "verify")
    assert done.returncode == 1 and "VIOLATED" in done.stdout and "DRIFT" in done.stdout


def test_goal_condition_is_usable_text(repo):
    repo.occam("goal", "init", "totals are correct")
    assert "goal verify" in repo.occam("goal", "condition").stdout


def test_gate_blocks_a_stub_and_passes_clean_work(repo):
    repo.write("app/new.py", "def charge(card):\n    pass\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "stub-body" in done.stdout and "NOT READY" in done.stdout
    repo.write("app/new.py", "def charge(card):\n    return card.pay()\n")
    repo.write("app/core.py", "from app.new import charge\n\n\ndef total(a, b):\n    if a > 0 and b > 0:\n        return a + b\n    return charge(a)\n")
    repo.write("tests/test_core.py", "from app.core import total\n\n\ndef test_total():\n    assert total(1, 2) == 3\n")
    done = repo.occam("gate")
    assert "stub-body" not in done.stdout
    assert "Checks only you can make" in done.stdout


def test_gate_sees_weakened_tests(repo):
    repo.write("tests/test_core.py", "from app.core import total\n\n\ndef test_total():\n    assert total(1, 2) == 3\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "test-weakened" in done.stdout


def test_gate_sees_a_deleted_test(repo):
    repo.write("tests/test_core.py", "from app.core import total\n")
    done = repo.occam("gate")
    assert done.returncode == 1 and "Removed tests: test_total" in done.stdout


def test_gate_notes_new_code_nothing_calls(repo):
    repo.write("app/core.py", repo.path.joinpath("app/core.py").read_text() + "\n\ndef helper_nobody_uses(x):\n    return x\n")
    assert "has no callers" in repo.occam("gate").stdout


def test_gate_notes_possible_duplicates_of_existing_helpers(repo):
    repo.write("app/dates.py", "def parse_date(s):\n    return s.strip()\n\n\nprint(parse_date('x'))\n")
    repo.commit()
    repo.write("app/other.py", "def parse_date_string(s):\n    return s\n\n\nprint(parse_date_string('x'))\n")
    assert "may duplicate" in repo.occam("gate").stdout


def test_gate_ignores_generated_output_in_the_diff(repo):
    (repo.path / ".gitignore").write_text("")
    repo.commit()
    repo.write("app/__pycache__/x.pyc", "junk")
    assert "No changes to gate" in repo.occam("gate").stdout


def test_gate_outside_git_takes_named_paths(tmp_path):
    made = Repo(tmp_path, tmp_path / ".state")
    made.write("a.py", "def charge(card):\n    pass\n")
    assert made.occam("gate").returncode == 2
    assert "stub-body" in made.occam("gate", "a.py").stdout


def test_committed_artifacts_are_reported_once_per_folder(repo):
    (repo.path / ".gitignore").write_text("")
    repo.write("app/__pycache__/a.pyc", "x")
    repo.write("app/__pycache__/b.pyc", "x")
    repo.commit()
    data = json.loads(repo.occam("scan", "--format", "json").stdout)
    assert len([f for f in data["findings"] if f["rule"] == "committed-artifact"]) == 1


def test_partition_says_zero_agents_for_small_work(repo):
    plan = json.loads(repo.occam("partition", "--format", "json").stdout)
    assert plan["agents"] == 0


def test_partition_scales_readers_and_caps_them(repo):
    for index in range(8):
        repo.write(f"pkg{index}/mod.py", "x = 1\n" * 5000)
    plan = json.loads(repo.occam("partition", "--format", "json", "--max-agents", "3").stdout)
    assert plan["agents"] == 3 and "Capped" in plan["reason"]
    files = [f for shard in plan["shards"] for f in shard["files"]]
    assert len(files) == len(set(files)), "shards must be disjoint"


def test_partition_keeps_coupled_files_together_for_writers(repo):
    repo.write("a/one.py", "from a.two import x\nprint(x)\n")
    repo.write("a/two.py", "x = 1\n")
    repo.write("b/three.py", "y = 1\n")
    plan = json.loads(repo.occam("partition", "--format", "json", "--mode", "write", "--budget", "2").stdout)
    for shard in plan["shards"]:
        assert ("a/one.py" in shard["files"]) == ("a/two.py" in shard["files"])
    assert plan["agents"] <= 3


def test_reuse_finds_existing_helpers_and_libraries(repo):
    repo.write("app/retry.py", "def retry_with_backoff(fn):\n    return fn()\n")
    done = repo.occam("reuse", "retry", "backoff").stdout
    assert "app/retry.py:1" in done and "tenacity" in done


def test_deps_reports_phantoms_and_unused(repo):
    repo.write("pyproject.toml", '[project]\nname = "x"\ndependencies = ["requests", "httpx", "boto3"]\n')
    repo.write("app/a.py", "import requests\nimport totally_made_up_pkg\nprint(requests, totally_made_up_pkg)\n")
    done = repo.occam("deps").stdout
    assert "phantom-import" in done and "totally_made_up_pkg" in done and "unused-dependency" in done and "competing-dependencies" in done


def test_tools_lists_and_never_runs_repo_code_unasked(repo):
    repo.write("eslint.config.js", "require('fs').writeFileSync('ran', 'x')\n")
    listing = repo.occam("tools").stdout
    assert "ruff" in listing or "semgrep" in listing or "gitleaks" in listing
    repo.occam("tools", "--run")
    assert not (repo.path / "ran").exists()


def test_runs_outside_any_repository(tmp_path):
    made = Repo(tmp_path, tmp_path / ".state")
    made.write("a.py", "def f(x=[]):\n    return x\n")
    assert "mutable-default" in made.occam("scan").stdout


def test_unwritable_state_doesnt_stop_a_scan(repo, tmp_path):
    env_state = tmp_path / "ro"
    env_state.mkdir()
    env_state.chmod(0o500)
    repo.env["OCCAM_STATE_DIR"] = str(env_state)
    repo.env["HOME"] = str(tmp_path)
    done = repo.occam("scan")
    env_state.chmod(0o700)
    assert done.returncode == 0


def test_tools_wont_run_a_binary_the_repository_ships(repo, tmp_path):
    marker = tmp_path / "ran"
    repo.write(".venv/bin/ruff", f"#!/bin/sh\ntouch {marker}\n")
    (repo.path / ".venv/bin/ruff").chmod(0o755)
    repo.write("a.py", "x = 1\n")
    assert "needs --allow-exec" in repo.occam("tools").stdout
    done = repo.occam("tools", "--run", "--only", "ruff")
    assert "not run" in done.stdout and not marker.exists()
    repo.occam("tools", "--run", "--allow-exec", "--only", "ruff")
    assert marker.exists()


def test_a_symlink_out_of_the_repository_isnt_read(repo, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text('API_KEY = "abc123def456ghi789"\n')
    (repo.path / "linked.py").symlink_to(outside)
    assert "hardcoded-secret" not in repo.occam("scan").stdout
