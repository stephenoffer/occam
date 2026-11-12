"""A pass from scan or gate means what was asked for was read and checked: nothing unread, unparsed, misnamed or compared with the
wrong commit can come back clean. Cases from the 2026-11-11 audit (O010–O014, O021, O022, O030, O031)."""

from __future__ import annotations

import json
import subprocess
import sys

from query_support import OCCAM, TOKEN, python_repo

sys.path.insert(0, str(OCCAM.parent))
from occam_tools import report, scan  # noqa: E402

MUTABLE = "def f(x=[]):\n    return x\n"


def stdin_scan(text: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(OCCAM), "scan", "--stdin", *args], input=text, capture_output=True, text=True, timeout=60)


def test_a_named_file_too_large_to_read_cant_pass(tmp_path):
    repo = python_repo(tmp_path, {"big.py": MUTABLE + "# pad\n" * 300_000, "ok.py": "x = 1\n"})
    done = repo.occam("scan", "big.py", "--fail-on", "high", "--no-cache")
    assert done.returncode == 1 and "INCOMPLETE" in done.stderr and "big.py" in done.stderr
    assert repo.occam("scan", "ok.py", "--fail-on", "high", "--no-cache").returncode == 0


def test_a_lockfile_too_large_to_read_isnt_a_gap(tmp_path):
    repo = python_repo(tmp_path, {"package-lock.json": json.dumps({"x": "y" * 2_000_000}), "ok.py": "x = 1\n"})
    done = repo.occam("scan", ".", "--fail-on", "high", "--no-cache")
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_notebook_that_doesnt_parse_cant_pass(tmp_path):
    bad_cell = {"cells": [{"cell_type": "code", "source": ["def f(:\n"], "metadata": {}, "outputs": [], "execution_count": None}],
                "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    repo = python_repo(tmp_path, {"bad.ipynb": "{", "cell.ipynb": json.dumps(bad_cell)})
    for name in ("bad.ipynb", "cell.ipynb"):
        done = repo.occam("scan", name, "--fail-on", "high", "--no-cache")
        assert done.returncode == 1 and "unparseable" in done.stdout, name


def test_repository_rules_cut_by_a_time_limit_are_a_gap_but_a_scoped_read_isnt():
    timed = {"partial": {"reason": "time", "read": 3, "wanted": 3, "unread_in_scope": 0}, "unscanned": []}
    scoped = {"partial": {"reason": "scope", "read": 3, "wanted": 3, "unread_in_scope": 0}, "unscanned": []}
    assert report.incomplete(timed) and not report.incomplete(scoped) and not report.incomplete({"unscanned": ["big.json"], "unread_code": []})


def test_a_staged_secret_in_a_config_file_is_gated_without_printing_it(tmp_path):
    repo = python_repo(tmp_path, {"settings.json": '{"a": 1}\n', "app.py": "x = 1\n"})
    repo.write("settings.json", json.dumps({"api_key": TOKEN}) + "\n")
    repo.git("add", "settings.json")
    repo.write("settings.json", '{"a": 1}\n')
    for args in ((), ("settings.json",)):
        done = repo.occam("gate", *args)
        assert done.returncode == 1 and "hardcoded-secret" in done.stdout and TOKEN not in done.stdout + done.stderr, args


def test_naming_a_path_still_reads_its_staged_version(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "x = 1\n", "other.py": "y = 1\n"})
    repo.write("app.py", "import pickle\n\n\ndef load(blob):\n    return pickle.loads(blob)\n")
    repo.git("add", "app.py")
    repo.write("app.py", "x = 1\n")
    named = repo.occam("gate", "app.py")
    assert named.returncode == 1 and "unsafe-deserialize" in named.stdout
    assert "unsafe-deserialize" not in repo.occam("gate", "other.py").stdout


def test_a_defect_added_on_a_branch_stays_new_when_the_base_later_adds_it_too(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "def ok():\n    return 1\n"})
    repo.git("branch", "-M", "main")
    repo.git("checkout", "-qb", "feature")
    repo.write("app.py", "def ok():\n    return 1\n\n\n" + MUTABLE)
    repo.commit("feature")
    repo.git("checkout", "-q", "main")
    repo.write("app.py", "def ok():\n    return 1\n\n\n" + MUTABLE)
    repo.commit("main gets it too")
    repo.git("checkout", "-q", "feature")
    done = repo.occam("scan", "--diff", "main", "--fail-on", "high", "--no-cache")
    assert done.returncode == 1 and "mutable-default" in done.stdout


def test_only_a_comment_suppresses():
    assert stdin_scan('s = "occam: ignore"\n' + MUTABLE, "--fail-on", "high").returncode == 1
    assert stdin_scan("# occam: ignore[mutable-default]\n" + MUTABLE, "--fail-on", "high").returncode == 0
    assert stdin_scan(MUTABLE.replace("):", "):  # occam: ignore", 1), "--fail-on", "high").returncode == 0


def test_a_long_string_doesnt_make_a_file_generated_and_a_bundle_is_still_read_for_keys():
    assert stdin_scan('SQL = "' + "a" * 1600 + '"\n' + MUTABLE, "--fail-on", "high").returncode == 1
    bundle = scan.analyze_text("dist/app.min.js", "var a=1;" * 400 + f'\nvar k="{TOKEN}";\n')
    assert bundle.get("generated") and [f["rule"] for f in bundle["findings"]] == ["hardcoded-secret"]


def test_a_misspelled_rule_is_an_error_not_a_clean_scan(tmp_path):
    done = stdin_scan(MUTABLE, "--rule", "mutable-defualt", "--fail-on", "high")
    assert done.returncode == 2 and "mutable-default" in done.stderr
    assert stdin_scan(MUTABLE, "--rule", "mutable-default", "--fail-on", "high").returncode == 1
    repo = python_repo(tmp_path, {"app.py": "x = 1\n", ".occam.json": '{"disable": ["no-such-rule"]}\n'})
    assert "no-such-rule" in repo.occam("scan", ".", "--no-cache").stderr


# ------------------------------------------------------------ goal verification (O015–O017, O036–O039)


def goal(repo, *args):
    return repo.occam("goal", *args)


def test_a_check_that_changes_the_files_doesnt_verify_the_tree(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "value = 1\n", "rewrite.py": 'import pathlib\npathlib.Path("app.py").write_text("value = 2\\n")\n'})
    goal(repo, "init", "keep the value")
    goal(repo, "add", "runs", "--check", f"{sys.executable} rewrite.py")
    done = goal(repo, "verify")
    assert done.returncode == 1 and "ALL VERIFIED" not in done.stdout and "changed while the checks ran" in done.stdout


def test_an_edit_git_was_told_not_to_watch_makes_old_evidence_stale(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "value = 1\n"})
    repo.git("update-index", "--assume-unchanged", "app.py")
    goal(repo, "init", "g")
    goal(repo, "add", "ok", "--check", f"{sys.executable} -c pass")
    assert goal(repo, "verify").returncode == 0
    repo.write("app.py", "value = 9\n")
    assert "stale" in goal(repo, "status").stdout


def test_outside_git_an_edit_with_its_time_put_back_is_still_seen(tmp_path):
    import os
    project = tmp_path / "plain"
    project.mkdir()
    (project / "app.py").write_text("value = 1\n")
    env = {**os.environ, "OCCAM_STATE_DIR": str(tmp_path / "state")}

    def run(*args):
        return subprocess.run([sys.executable, str(OCCAM), "goal", *args], cwd=project, env=env, capture_output=True, text=True, timeout=60)
    run("init", "g")
    run("add", "ok", "--check", f"{sys.executable} -c pass")
    assert run("verify").returncode == 0
    before = os.stat(project / "app.py")
    (project / "app.py").write_text("value = 9\n")
    os.utime(project / "app.py", ns=(before.st_atime_ns, before.st_mtime_ns))
    assert "stale" in run("status").stdout


def test_an_api_the_comparison_cant_read_isnt_called_kept(tmp_path):
    repo = python_repo(tmp_path, {"pkg/mod.swift": "public func fetch(x: Int) -> Int { return x }\n"})
    goal(repo, "init", "keep the API")
    goal(repo, "constrain", "keep the public API", "--no", "api-break")
    repo.write("pkg/mod.swift", "public func fetch(y: String) -> Int { return 1 }\n")
    repo.commit("change")
    goal(repo, "add", "ok", "--check", f"{sys.executable} -c pass")
    done = goal(repo, "verify")
    assert done.returncode == 1 and "NOT CHECKED" in done.stdout and "swift" in done.stdout


def test_results_arent_recorded_on_a_goal_replaced_while_checks_ran(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "x = 1\n"})
    replace = (f"import subprocess, sys; subprocess.run([sys.executable, {str(OCCAM)!r}, 'goal', 'clear']); "
               f"subprocess.run([sys.executable, {str(OCCAM)!r}, 'goal', 'init', 'another']); "
               f"subprocess.run([sys.executable, {str(OCCAM)!r}, 'goal', 'add', 'other', '--check', 'false'])")
    repo.write("replace.py", replace + "\n")
    repo.commit("helper")
    goal(repo, "init", "first")
    goal(repo, "add", "replaces the goal", "--check", f"{sys.executable} replace.py")
    done = goal(repo, "verify")
    assert done.returncode == 1 and "cleared or replaced" in done.stdout and "Traceback" not in done.stderr
    assert "R1 not run" in goal(repo, "status").stdout.replace("  ", " ")


def test_two_inits_at_once_leave_one_goal_and_one_refusal(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "x = 1\n"})
    runs = [subprocess.Popen([sys.executable, str(OCCAM), "goal", "init", f"goal {i}"], cwd=repo.path, env=repo.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
    outcomes = [run.wait(timeout=60) for run in runs]
    assert outcomes.count(0) == 1 and outcomes.count(2) == 3


# ------------------------------------------------------------ state per worktree and per repository (O040, O041)


def test_worktrees_keep_their_own_goals_but_share_claims(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "x = 1\n"})
    other = tmp_path / "other-worktree"
    repo.git("worktree", "add", "-q", str(other))
    assert goal(repo, "init", "first task").returncode == 0
    second = repo.occam("goal", "init", "second task", cwd=other)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "first task" in goal(repo, "status").stdout and "second task" in repo.occam("goal", "status", cwd=other).stdout
    repo.occam("coord", "claim", "app.py", "--owner", "agent-a")
    assert "agent-a" in repo.occam("coord", "status", cwd=other).stdout


def test_one_state_folder_for_many_repositories_keeps_them_apart(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = python_repo(tmp_path / "a", {"app.py": "x = 1\n"})
    second = python_repo(tmp_path / "b", {"app.py": "x = 1\n"})
    second.env["OCCAM_STATE_DIR"] = first.env["OCCAM_STATE_DIR"]
    assert goal(first, "init", "repo a's goal").returncode == 0
    assert goal(second, "init", "repo b's goal").returncode == 0
    assert "repo a's goal" in goal(first, "status").stdout and "repo b's goal" in goal(second, "status").stdout


# ------------------------------------------------------------ ids, baselines and reports (O067, O069–O075, O104, O118)


def test_lines_that_differ_only_after_240_characters_get_different_ids():
    def finding_on_a_long_line(tail: str) -> dict:
        record = scan.analyze_text("app.py", f"import pickle\n\n\ndef load(blob):\n    return pickle.loads(blob) or '{'a' * 260}{tail}'\n")
        found = [f for f in record["findings"] if f["rule"] == "unsafe-deserialize"]
        scan._decorate(found)
        return found[0]
    assert finding_on_a_long_line("1")["id"] != finding_on_a_long_line("2")["id"]
    assert scan.fingerprint("r", "p", "a" * 300 + "1") != scan.fingerprint("r", "p", "a" * 300 + "2")
    assert scan.fingerprint("r", "p", "short line") == scan.fingerprint("r", "p", "short   line")


def test_a_cross_file_finding_keeps_its_id_when_only_its_line_numbers_move():
    one = {"rule": "clone-block", "path": "a.py", "line": 3, "message": "Same as b.py:10-20.", "evidence": ""}
    two = {**one, "message": "Same as b.py:14-24."}
    scan._decorate([one])
    scan._decorate([two])
    assert one["id"] == two["id"]


def test_a_baseline_says_how_it_was_made_and_an_old_one_warns(tmp_path):
    repo = python_repo(tmp_path, {"app.py": MUTABLE})
    out = tmp_path / "baseline.json"
    assert repo.occam("baseline", "write", "--out", str(out)).returncode == 0
    saved = json.loads(out.read_text())
    assert isinstance(saved, list) and set(saved[1:]) <= set(saved), "a list of ids, so an older occam still reads it"
    made = json.loads(saved[0].split(" ", 1)[1])
    assert made["ids"] == scan.IDENTITY_VERSION and "python" in made and saved[1:]
    assert repo.occam("scan", "--baseline", str(out), "--fail-on", "high").returncode == 0
    out.write_text(json.dumps(saved[1:]))
    done = repo.occam("scan", "--baseline", str(out), "--fail-on", "high")
    assert "made finding ids another way" in done.stderr


def test_sarif_says_whether_the_analysis_finished_and_names_paths_as_uris():
    finding = {"rule": "mutable-default", "path": "my dir/a#b%20.py", "line": 2, "message": "m", "severity": "high", "confidence": "high", "tier": "B", "id": "x"}
    cell = {**finding, "path": "nb.ipynb", "cell": 3, "line": 1}
    done = json.loads(report.render_sarif([finding, cell], {"unscanned": ["big.py"], "unread_code": ["big.py"], "partial": None}))["runs"][0]
    assert done["invocations"][0]["executionSuccessful"] is False and done["invocations"][0]["toolExecutionNotifications"]
    first, second = (result["locations"][0]["physicalLocation"] for result in done["results"])
    assert first["artifactLocation"]["uri"] == "my%20dir/a%23b%2520.py"
    assert "region" not in second and done["results"][1]["locations"][0]["properties"] == {"cell": 3, "lineInCell": 1}
    complete = json.loads(report.render_sarif([], {"unscanned": ["link.py"], "unread_code": [], "partial": None}))["runs"][0]  # a link isn't a gap
    assert complete["invocations"][0]["executionSuccessful"] is True


def test_markdown_and_text_reports_carry_every_limit_and_no_terminal_codes():
    stats = {"analyzed": 1, "files": 3, "lines": 10, "languages": {"python": 1}, "seconds": 0.1, "partial": None, "unscanned": ["big.py"],
             "generated": ["dist/app.min.js"], "skipped_by_name": 4, "suppressed_inline": 2, "config_ignored": [], "config_disabled": [], "isolated": False}
    markdown = report.render_markdown([], stats)
    for expected in ("big.py", "dist/app.min.js", "4 files in vendored", "2 findings were silenced"):
        assert expected in markdown, expected
    finding = {"rule": "mutable-default", "path": "evil\x1b[31m\nFAKE.py", "line": 1, "message": "m\x1b]0;x\x07", "severity": "high", "confidence": "high", "tier": "B",
               "category": report.BY_ID["mutable-default"].category, "score": 1.0, "id": "x"}
    text = report.render_text([finding], 0, stats, 5)
    assert "\x1b" not in text and "\x07" not in text and "\nFAKE.py" not in text


# ------------------------------------------------------------ strict gate, saved results, workers (O097, O100, O107, O108, O116)


def test_a_strict_gate_stops_on_what_it_couldnt_see(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "x = 1\n", "src/lib.py": "y = 1\n"})
    repo.git("update-index", "--assume-unchanged", "app.py")
    assert repo.occam("gate").returncode == 0
    assert repo.occam("gate", "--strict").returncode == 1
    repo.git("update-index", "--no-assume-unchanged", "app.py")
    goal(repo, "init", "only touch src")
    goal(repo, "scope", "src/")
    repo.write("app.py", "x = 2\n")
    done = repo.occam("gate", "--strict")
    assert done.returncode == 1 and "DRIFT" in done.stdout


def test_saved_scan_results_say_what_made_them(tmp_path):
    repo = python_repo(tmp_path, {"app.py": MUTABLE})
    repo.occam("scan", ".", "--no-cache")
    saved = json.loads(next((tmp_path / "s").rglob("last-scan.json")).read_text())
    assert saved["occam"] and saved["head"] and saved["command"][:1] == ["scan"] and saved["findings"]


def test_workers_fit_the_memory_there_is(monkeypatch):
    monkeypatch.setattr(scan.os, "sysconf", lambda name: 4096 if name == "SC_PAGE_SIZE" else 5 * scan.WORKER_BYTES // 2 // 4096)  # room for two and a half
    monkeypatch.setattr(scan.Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(OSError()))
    assert scan.default_workers() == 2


def test_a_hook_skips_a_fifo_named_like_code(tmp_path):
    import os
    os.mkfifo(tmp_path / "app.py")
    probe = f"import sys; sys.path.insert(0, {str(OCCAM.parents[3] / 'hooks')!r}); import scan_notes, pathlib; print(scan_notes._read(pathlib.Path({str(tmp_path / 'app.py')!r})))"
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=20)  # reading one would wait forever, and fail this by timing out
    assert done.stdout.strip() == "None", done.stderr


# ------------------------------------------------------------ coverage reports (O119, O120)


def test_valid_coverage_xml_in_any_spelling_is_read(tmp_path):
    from occam_tools import query_graph
    xml = ("<?xml version='1.0'?><coverage><sources><source>" + str(tmp_path / "src") + "</source></sources><packages>"
           "<ns:class\n name='a' filename = 'app/a&amp;b.py' line-rate=\"1e-05\"/><class\tname='b' filename='app/c.py' line-rate='0.5'/></packages></coverage>")
    rates = query_graph._coverage_rates("coverage.xml", xml, tmp_path)
    assert rates["app/a&b.py"] == 1e-05 and rates["src/app/c.py"] == 0.5


def test_the_newest_coverage_report_is_the_one_used(tmp_path):
    import os
    from occam_tools import query_graph
    (tmp_path / "coverage.xml").write_text('<coverage><class filename="old.py" line-rate="0.1"/></coverage>')
    (tmp_path / "lcov.info").write_text("SF:new.py\nLF:4\nLH:4\nend_of_record\n")
    os.utime(tmp_path / "coverage.xml", (1_000_000, 1_000_000))
    assert query_graph._read_coverage(tmp_path)["file"] == "lcov.info"


def test_registry_text_cant_drive_the_terminal():
    from occam_tools import depcheck
    shown = depcheck._render({"registry": "pypi", "name": "x", "status": "exists", "summary": "evil\x1b[31m\nFAKE: not found", "repository": "https://x"})
    assert "\x1b" not in shown and "\n" not in shown



# ------------------------------------------------------------ from the second review


def test_links_utf16_files_and_notebooks_with_plots_dont_fail_a_scan(tmp_path):
    import os
    notebook = {"cells": [{"cell_type": "code", "source": ["x = 1\n"], "metadata": {}, "execution_count": 1,
                           "outputs": [{"output_type": "display_data", "data": {"image/png": "A" * 1_700_000}, "metadata": {}}]}],
                "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    repo = python_repo(tmp_path, {"app.py": "x = 1\n", "plots.ipynb": json.dumps(notebook)})
    os.symlink("app.py", repo.path / "link.py")
    (repo.path / "Setup.ps1").write_bytes("Write-Host hi\n".encode("utf-16"))
    repo.commit("more")
    done = repo.occam("scan", ".", "--fail-on", "high", "--no-cache")
    assert done.returncode == 0, done.stdout + done.stderr


def test_ipython_syntax_isnt_a_broken_notebook_but_a_real_error_is_found_in_its_cell(tmp_path):
    def notebook(*sources):
        return json.dumps({"cells": [{"cell_type": "code", "source": source, "metadata": {}, "outputs": [], "execution_count": None} for source in sources],
                           "metadata": {}, "nbformat": 4, "nbformat_minor": 5})
    magics = notebook(["x = 1\n"], ["%%writefile run.sh\n", "echo hi\n"], ["len?\n"], ["%%bash\n", "ls -la | wc\n"])
    assert not [f for f in scan.analyze_text("a.ipynb", magics)["findings"] if f["rule"] == "unparseable"]
    broken = [f for f in scan.analyze_text("b.ipynb", notebook(["x = 1\n"], ["%%time\n", "y = [\n"]))["findings"] if f["rule"] == "unparseable"]
    assert broken and broken[0]["cell"] == 2


def test_a_sparse_checkout_isnt_files_git_was_told_not_to_watch(tmp_path):
    repo = python_repo(tmp_path, {"src/app.py": "x = 1\n", "docs/a.py": "y = 1\n"})
    repo.git("sparse-checkout", "set", "src")
    assert repo.occam("gate", "--strict").returncode == 0


def test_a_change_to_shell_or_sql_doesnt_leave_the_api_unchecked(tmp_path):
    repo = python_repo(tmp_path, {"pkg/mod.py": "def f(x):\n    return x\n", "run.sh": "echo a\n", "schema.sql": "select 1;\n"})
    goal(repo, "init", "keep the API")
    goal(repo, "constrain", "keep it", "--no", "api-break")
    goal(repo, "add", "ok", "--check", f"{sys.executable} -c pass")
    repo.write("run.sh", "echo b\n")
    repo.write("schema.sql", "select 2;\n")
    done = goal(repo, "verify")
    assert done.returncode == 0, done.stdout


def test_bytecode_a_check_writes_doesnt_make_its_result_stale(tmp_path):
    repo = python_repo(tmp_path, {"app.py": "x = 1\n", "tests/test_app.py": "import app\n\n\ndef test_x():\n    assert app.x == 1\n"})
    repo.write(".gitignore", "")
    repo.commit("no ignores")
    goal(repo, "init", "g")
    goal(repo, "add", "tests", "--check", f"{sys.executable} -m pytest -q -p no:cacheprovider")
    first = goal(repo, "verify")
    assert first.returncode == 0, first.stdout
    assert "verified" in goal(repo, "status").stdout


def test_a_comment_occam_doesnt_model_still_suppresses(tmp_path):
    terraform = 'resource "aws_s3_bucket" "b" {\n  // occam: ignore\n  acl = "public-read"\n}\n'
    record = scan.analyze_text("main.tf", terraform)
    plain = scan.analyze_text("main.tf", terraform.replace("  // occam: ignore\n", "  // fine\n"))
    assert len(record["findings"]) < len(plain["findings"]) or not plain["findings"]
    php = "<?php\n# occam: ignore\n$x = unserialize($_GET['a']);\n"
    assert not [f for f in scan.analyze_text("a.php", php)["findings"] if f["rule"] == "unsafe-deserialize"]
    assert [f for f in scan.analyze_text("a.php", php.replace("# occam: ignore", "# fine"))["findings"] if f["rule"] == "unsafe-deserialize"]
    docstring = 'def g():\n    """\n    occam: ignore\n    """\n\n\ndef f(x=[]):\n    return x\n'
    assert [f for f in scan.analyze_text("a.py", docstring)["findings"] if f["rule"] == "mutable-default"]


def test_long_and_triple_quoted_strings_dont_make_a_file_generated():
    for text in ('SQL = "' + "a" * 4100 + '"\n' + MUTABLE, 'CERT = """\n' + "b" * 1700 + '\n"""\n' + MUTABLE):
        assert [f for f in scan.analyze_text("app.py", text)["findings"] if f["rule"] == "mutable-default"]


# ------------------------------------------------------------ from the second review round


def test_a_report_a_check_leaves_behind_doesnt_make_its_result_stale(tmp_path):
    writer = 'import pathlib, time\npathlib.Path("junit.xml").write_text(str(time.time()))\n'
    repo = python_repo(tmp_path, {"app.py": "x = 1\n", "report.py": writer})
    goal(repo, "init", "g")
    goal(repo, "add", "writes a report", "--check", f"{sys.executable} report.py")
    for _ in range(2):
        assert goal(repo, "verify").returncode == 0
        assert "verified" in goal(repo, "status").stdout


def test_packages_named_for_their_import_plus_a_suffix_are_declared(tmp_path):
    names = ["kafka-python", "websocket-client", "paho-mqtt", "mysql-connector-python", "argon2-cffi", "cassandra-driver"]
    code = "import kafka\nimport websocket\nimport paho.mqtt.client\nimport mysql.connector\nimport argon2\nimport cassandra\n"
    repo = python_repo(tmp_path, {"requirements.txt": "\n".join(names) + "\n", "app/main.py": code + "print(kafka, websocket, paho, mysql, argon2, cassandra)\n"})
    found = repo.occam("scan", ".", "--no-cache", "--format", "json").stdout
    rules = [(f["rule"], f["message"]) for f in json.loads(found)["findings"] if f["rule"] in ("phantom-import", "undeclared-dependency", "unused-dependency")]
    assert not rules, rules
    from occam_tools import imports
    assert not imports.dist_matches("flask-login", "flask") and not imports.dist_matches("requests-mock", "requests")


def test_a_deep_go_package_path_is_found_as_its_module(monkeypatch):
    from occam_tools import depcheck
    asked = []
    monkeypatch.setattr(depcheck, "_fetch", lambda url: (asked.append(url), (200, {"Version": "v0.1.0"}) if url.endswith("k8s.io/apimachinery/@latest") else (404, {}))[1])
    assert depcheck.check_package("go", "k8s.io/apimachinery/pkg/apis/meta/v1")["status"] == "exists"


def test_code_beside_a_manifest_in_a_sibling_folder_is_covered_by_it(tmp_path):
    repo = python_repo(tmp_path, {"docker/requirements.txt": "requests\n", "app/main.py": "import requests\nprint(requests)\n"})
    found = json.loads(repo.occam("scan", ".", "--no-cache", "--format", "json").stdout)["findings"]
    assert not [f for f in found if f["rule"] == "phantom-import"]


def test_a_dependency_added_only_in_an_included_file_or_a_setup_helper_is_new(tmp_path):
    from occam_tools import workflow
    repo = python_repo(tmp_path, {"requirements.txt": "-r base.txt\n", "base.txt": "flask\n",
                                  "setup.py": "import runpy\ndeps = runpy.run_path('dependencies.py')\nsetup(install_requires=deps['install_requires'])\n",
                                  "dependencies.py": "install_requires = ['attrs']\n"})
    repo.write("base.txt", "flask\nleftpad\n")
    repo.write("dependencies.py", "install_requires = ['attrs', 'rightpad']\n")
    added = workflow.new_dependencies(repo.path, "HEAD", ["base.txt", "dependencies.py"])
    assert any(item.startswith("leftpad") for item in added) and any(item.startswith("rightpad") for item in added), added


def test_online_phantom_checks_set_the_exit_code(monkeypatch, tmp_path):
    from occam_tools import depcheck
    monkeypatch.setenv("OCCAM_STATE_DIR", str(tmp_path / "state"))
    repo = python_repo(tmp_path, {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n', "app/a.py": "import flask_superauth\nprint(flask_superauth)\n"})
    monkeypatch.setattr(depcheck, "_fetch", lambda url: (404, {}))
    assert depcheck.report(repo.path, online=True)[1] == 1
    monkeypatch.setattr(depcheck, "_fetch", lambda url: (0, {}))
    assert depcheck.report(repo.path, online=True)[1] == 2


def test_api_readings_the_second_review_found_wrong(tmp_path):
    cases = [
        ("from dataclasses import dataclass\n@dataclass\nclass P:\n    x: int\n", "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass P:\n    x: int\n", True),
        ("def f(x):\n    return x\n", "from warnings import deprecated\n@deprecated('use g')\ndef f(x):\n    return x\n", False),
        ("from functools import cache\n@cache\ndef f(x):\n    return x\n", "import functools\n@functools.cache\ndef f(x):\n    return x\n", False),
        ("def f(a, /):\n    return a\n", "def f(b):\n    return b\n", False),
    ]
    for before, after, breaks in cases:
        root = tmp_path / f"r{cases.index((before, after, breaks))}"
        root.mkdir()
        repo = python_repo(root, {"pkg/mod.py": before})
        repo.git("branch", "-M", "main")
        repo.git("checkout", "-qb", "f")
        repo.write("pkg/mod.py", after)
        repo.commit("change")
        data = json.loads(repo.occam("query", "api", "--base", "main", "--format", "json").stdout)
        reasons = [reason for row in data["changed"] for reason in row["breaking"] + row.get("defaults", [])] + [row["name"] for row in data["removed"]]
        assert bool(reasons) is breaks, (after, reasons)


def test_mutate_cant_write_into_the_project_through_a_link(tmp_path):
    import os
    repo = python_repo(tmp_path, {"lib.py": "def add(a, b):\n    return a + b\n", "data.txt": "keep\n",
                                  "tests/test_lib.py": "import pathlib\nfrom lib import add\n\n\ndef test_add():\n    if add(1, 2) != 3:\n        pathlib.Path('link.txt').write_text('changed')\n    assert add(1, 2) == 3\n"})
    os.symlink(str(repo.path / "data.txt"), repo.path / "link.txt")
    repo.commit("link")
    repo.occam("mutate", "--cmd", f"{sys.executable} -m pytest -q -p no:cacheprovider", "lib.py")
    assert (repo.path / "data.txt").read_text() == "keep\n"


def test_what_a_command_left_running_is_stopped_when_it_finishes(tmp_path):
    import time
    from occam_tools import files
    marker = tmp_path / "late"
    files.run_bounded(["sh", "-c", f"(sleep 0.5; touch {marker}) >/dev/null 2>&1 & echo started"], tmp_path, 10)
    time.sleep(1.2)
    assert not marker.exists()


def test_golden_wont_record_output_it_cant_keep_whole(tmp_path):
    from occam_tools import measure
    try:
        measure._run_for_golden(tmp_path, [sys.executable, "-c", "print('x' * 9_000_000)"], 60)
    except measure.CommandFailed as error:
        assert "8 MB" in str(error)
    else:
        raise AssertionError("an output cut in the middle was recorded as if whole")


def test_a_tool_asked_for_by_name_that_didnt_run_fails_the_run(tmp_path, monkeypatch):
    from occam_tools import toolrun
    monkeypatch.setattr(toolrun, "_locate", lambda root, name: (None, False))
    (tmp_path / "a.py").write_text("x = 1\n")
    text, code = toolrun.run_tools(tmp_path, execute=True, only=["ruff"])
    assert code == 1 and "not installed" in text


def test_bench_reads_startup_heavy_runs_as_they_grow():
    from occam_tools import measure
    sizes = [1.0, 10.0, 100.0, 1000.0]
    linear, why = measure._growth(sizes, [1 + 0.001 * n for n in sizes])
    assert linear is not None and 0.8 < linear < 1.25, why
    quadratic, why = measure._growth([100.0, 200.0, 400.0, 800.0], [10 + 1e-6 * n * n for n in (100, 200, 400, 800)])
    assert quadratic is not None and quadratic > 1.8, why


# ------------------------------------------------------------ from the third review round


def test_a_new_module_a_check_rewrites_isnt_verified(tmp_path):
    rewrite = 'import pathlib\npathlib.Path("newmod.py").write_text("def f():\\n    return 2\\n")\n'
    repo = python_repo(tmp_path, {"app.py": "x = 1\n", "rewrite.py": rewrite})
    repo.write("newmod.py", "def f():\n    return 1\n")  # new work, not yet added
    goal(repo, "init", "g")
    goal(repo, "add", "runs", "--check", f"{sys.executable} rewrite.py")
    done = goal(repo, "verify")
    assert done.returncode == 1 and "ALL VERIFIED" not in done.stdout


def test_a_manifest_for_another_language_doesnt_hide_the_python_one(tmp_path):
    repo = python_repo(tmp_path, {"package.json": '{"devDependencies": {"prettier": "3"}}', "docker/requirements.txt": "requests\nflask\n",
                                  "app/main.py": "import requests\nimport flask\nprint(requests, flask)\n"})
    found = json.loads(repo.occam("scan", ".", "--no-cache", "--format", "json").stdout)["findings"]
    assert not [f for f in found if f["rule"] in ("phantom-import", "undeclared-dependency")], found


def test_a_strict_gate_on_named_paths_says_why_it_fails(tmp_path):
    repo = python_repo(tmp_path, {"calc.py": "def add(a, b):\n    return a + b\n", "other.py": "y = 1\n",
                                  "test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"})
    repo.git("update-index", "--skip-worktree", "other.py")
    repo.write("calc.py", "def add(a, b):\n    return b + a\n")
    assert repo.occam("gate", "--strict", "calc.py", "test_calc.py").returncode == 0  # the unwatched file isn't among them
    done = repo.occam("gate", "--strict", ".")
    assert done.returncode == 1 and "not to watch" in done.stdout


def test_respelling_dataclass_arguments_isnt_a_break(tmp_path):
    cases = [("@dataclass\n", "@dataclass()\n"), ("@dataclass(frozen=True, order=True)\n", "@dataclass(order=True, frozen=True)\n")]
    for index, (before, after) in enumerate(cases):
        (tmp_path / str(index)).mkdir()
        repo = python_repo(tmp_path / str(index), {"pkg/mod.py": "from dataclasses import dataclass\n" + before + "class P:\n    x: int\n"})
        repo.git("branch", "-M", "main")
        repo.git("checkout", "-qb", "f")
        repo.write("pkg/mod.py", "from dataclasses import dataclass\n" + after + "class P:\n    x: int\n")
        repo.commit("respell")
        data = json.loads(repo.occam("query", "api", "--base", "main", "--format", "json").stdout)
        assert not [reason for row in data["changed"] for reason in row["breaking"]], (after, data["changed"])


def test_js_with_no_package_json_above_it_is_still_checked(tmp_path):
    repo = python_repo(tmp_path, {"web/package.json": '{"dependencies": {"react": "18"}}', "scripts/tool.js": "const _ = require('lodash-made-up');\nconsole.log(_);\n"})
    found = json.loads(repo.occam("scan", ".", "--no-cache", "--format", "json").stdout)["findings"]
    assert [f for f in found if f["path"] == "scripts/tool.js" and f["rule"] == "phantom-import"], found


# ------------------------------------------------------------ the last open findings (O068, O095, O096, O115)


def test_a_copy_added_in_another_function_doesnt_move_the_others_ids():
    block = "def {name}():\n    try:\n        run()\n    except Exception:\n        pass\n\n\n"
    def ids(names):
        found = [f for f in scan.analyze_text("app.py", "".join(block.format(name=n) for n in names))["findings"] if f["rule"] == "swallowed-exception"]
        scan._decorate(found)
        return {f["scope"]: f["id"] for f in found}
    before, after = ids(["a", "b"]), ids(["new", "a", "b"])
    assert before["a"] == after["a"] and before["b"] == after["b"] and after["new"] not in before.values()


SWALLOWED = "def {name}():\n    try:\n        run()\n    except Exception:\n        pass\n\n\n"


def test_the_first_copy_added_or_the_last_one_removed_doesnt_make_the_one_there_new():
    def found(names):
        found = [f for f in scan.analyze_text("app.py", "".join(SWALLOWED.format(name=n) for n in names))["findings"] if f["rule"] == "swallowed-exception"]
        scan._decorate(found)
        return found

    def new(before, after):
        known = set(scan.ids_of(found(before)))
        return sorted(f["scope"] for f in found(after) if f["id"] not in known)

    assert new(["a"], ["a", "b"]) == ["b"]  # a copy added below the one there
    assert new(["b"], ["a", "b"]) == ["a"]  # and above it, which used to move the old id to the copy
    assert new(["a", "b"], ["b"]) == []  # the last copy removed
    assert new(["a"], ["renamed"]) == []  # a lone finding stays itself when its function is renamed
    assert new(["a"], ["a", "a"]) == ["a"]  # two in one function can't be told apart, but only one counts as new


def test_a_baseline_counts_only_the_copy_added_to_a_lone_finding(tmp_path):
    repo = python_repo(tmp_path, {"app.py": SWALLOWED.format(name="old")})
    out = tmp_path / "baseline.json"

    def count():
        return len(json.loads(repo.occam("scan", "--no-cache", "--format", "json").stdout)["findings"])

    assert f"Baseline of {count()} findings" in repo.occam("baseline", "write", "--out", str(out)).stdout  # not its count of ids
    repo.write("app.py", SWALLOWED.format(name="added") + SWALLOWED.format(name="old"))
    found = json.loads(repo.occam("scan", "--no-cache", "--baseline", str(out), "--format", "json").stdout)["findings"]
    assert [(f["rule"], f["line"]) for f in found if f["rule"] == "swallowed-exception"] == [("swallowed-exception", 4)], found
    repo.occam("baseline", "write")
    assert f"holds {count()} findings" in repo.occam("baseline", "show").stdout
