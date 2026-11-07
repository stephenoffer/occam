"""`occam query`, one question at a time, run for real through the command line against real repositories."""

from __future__ import annotations

import json
import subprocess

import pytest
from query_support import API, CORE, FILES, GIT, TOKEN, Repo, make_repo


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo", tmp_path / "state")


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """A repository no test changes, so the read-only queries needn't each build one."""
    base = tmp_path_factory.mktemp("shared")
    return make_repo(base / "repo", base / "state")


def names_at(data: dict, group: str) -> list[str]:
    return [row["where"] for row in data["groups"].get(group, [])]


# ---------------------------------------------------------------- size

def test_size_counts_as_wc_does_and_leaves_vendored_code_out(shared):
    data = shared.query("size")
    expected = sum(content.count("\n") for name, content in FILES.items() if name.endswith((".py", ".sh")) and not name.startswith(("vendor/", "dist/"))) + FILES["bin/noext"].count("\n")
    assert data["lines"] == expected
    assert "vendor/pkg/lib.py" not in [row["path"] for row in data["largest_files"]]
    assert data["left_out"] == 2


def test_size_counts_files_per_language(repo):
    repo.write("a.go", "package a\n\nvar X = 1\n")
    assert repo.query("size")["languages"]["go"] == {"files": 1, "lines": 3}


def test_size_groups_by_directory_and_reports_test_share(shared):
    rows = {row["path"]: row for row in shared.query("size")["directories"]}
    assert rows["tests"]["test_lines"] == rows["tests"]["lines"] > 0
    assert rows["app"]["test_lines"] == 0
    assert set(rows) >= {"app", "tests", "web", "scripts", "."}


def test_size_of_a_path_groups_inside_it(shared):
    rows = {row["path"] for row in shared.query("size", "app")["directories"]}
    assert rows == {"app"}
    shared_rows = shared.query("size", "--depth", "1")["depth"]
    assert shared_rows == 1


def test_size_names_each_manifest_as_a_subsystem(repo):
    repo.write("services/a/go.mod", "module x\n")
    repo.write("services/a/main.go", "package main\n\nfunc main() {}\n")
    rows = {row["path"]: row["lines"] for row in repo.query("size")["subsystems"]}
    assert rows["services/a"] == 3 and rows["."] > 3


def test_size_warns_when_a_scan_would_be_huge(shared, monkeypatch):
    from occam_tools import query_repo
    data = {"lines": 9_000_000, "files": 1, "other_files": 0, "left_out": 0, "config_ignores": [], "languages": {}, "depth": 1, "directories": [], "directories_total": 0, "subsystems": [], "largest_files": []}
    assert "--isolated" in query_repo.render_size(data)
    data["lines"] = 1000
    assert "--isolated" not in query_repo.render_size(data)


def test_a_missing_path_is_an_error_not_an_empty_answer(shared):
    done = shared.occam("query", "size", "nowhere")
    assert done.returncode == 2 and "No such path" in done.stdout


def test_a_path_outside_the_named_root_is_an_error(shared, tmp_path):
    done = shared.occam("query", "size", str(tmp_path), "--root", str(shared.path))
    assert done.returncode == 2 and "outside this project" in done.stdout


def test_a_path_in_another_project_answers_for_that_project(shared, tmp_path):
    other = make_repo(tmp_path / "other", tmp_path / "state")
    assert shared.query("size", str(other.path / "app"))["files"] == other.query("size", "app")["files"]

# ---------------------------------------------------------------- outline

def test_outline_gives_nested_symbols_with_lines_and_signatures(shared):
    symbols = {row["name"]: row for row in shared.query("outline", "app/core.py")["files"][0]["symbols"]}
    assert symbols["total"]["line"] == 5 and symbols["total"]["end"] == 9 and "cap=None" in symbols["total"]["signature"]
    assert symbols["total"]["doc"] == "Add."
    assert symbols["Ledger"]["kind"] == "class"
    assert symbols["post"]["kind"] == "method" and symbols["post"]["depth"] == 1


def test_outline_indents_a_function_inside_a_function(repo):
    repo.write("n.py", "def outer():\n    def inner():\n        pass\n    return inner\n")
    symbols = {row["name"]: row["depth"] for row in repo.query("outline", "n.py")["files"][0]["symbols"]}
    assert symbols == {"outer": 0, "inner": 1}


def test_outline_reads_other_languages(repo):
    repo.write("a.go", "package a\n\nfunc Add(x int) int {\n\treturn x\n}\n")
    repo.write("a.sql", "CREATE TABLE IF NOT EXISTS users (id int);\n")
    repo.write("a.rb", "class Thing\n  def go\n  end\nend\n")
    data = repo.query("outline", "a.go", "a.sql", "a.rb", "scripts/lib.sh")["files"]
    found = {row["path"]: [symbol["name"] for symbol in row["symbols"]] for row in data}
    assert found == {"a.go": ["Add"], "a.sql": ["users"], "a.rb": ["Thing", "go"], "scripts/lib.sh": ["greet"]}


def test_outline_reads_a_notebook(repo):
    cell = {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": ["def clean(frame):\n", "    return frame\n"]}
    repo.write("a.ipynb", json.dumps({"cells": [cell], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))
    assert [row["name"] for row in repo.query("outline", "a.ipynb")["files"][0]["symbols"]] == ["clean"]


def test_outline_reports_a_file_that_doesnt_parse(repo):
    repo.write("bad.py", "def (:\n")
    assert repo.query("outline", "bad.py")["files"][0]["parse_error"]


def test_outline_needs_a_path(shared):
    assert shared.occam("query", "outline").returncode == 2

# ---------------------------------------------------------------- find

def test_find_separates_definition_import_call_string_comment_and_test(shared):
    data = shared.query("find", "total")
    assert names_at(data, "definition") == ["app/core.py:5"]
    assert "app/api.py:1" in names_at(data, "import")
    calls = {row["where"]: row["inside"] for row in data["groups"]["call"]}
    assert calls["app/core.py:14"] == "post" and calls["app/api.py:11"] == "load"
    assert "app/api.py:14" in names_at(data, "comment")
    assert {"app/api.py:15", "app/api.py:16"} <= set(names_at(data, "string"))
    assert "tests/test_core.py:5" in names_at(data, "test call")
    assert "tests/test_core.py:1" in names_at(data, "test import")
    assert "README.md:9" in names_at(data, "text")


def test_find_stays_out_of_vendored_code_unless_named(shared):
    assert not [row for rows in shared.query("find", "total")["groups"].values() for row in rows if row["path"].startswith("vendor/")]
    assert shared.query("find", "total", "vendor/pkg/lib.py")["total"] == 1


def test_find_matches_whole_words(repo):
    repo.write("app/other.py", "total_cost = 1\nsubtotal = 2\n")
    assert not [row for rows in repo.query("find", "total")["groups"].values() for row in rows if row["path"] == "app/other.py"]


def test_find_says_when_nothing_refers_to_a_name(repo):
    repo.write("app/only.py", "def nobody_calls_me():\n    return 1\n")
    data = repo.query("find", "nobody_calls_me")
    assert data["references"] == 0 and data["dynamic_use_exists"] is False
    assert "doesn't prove it unused" in repo.text("find", "nobody_calls_me")
    repo.write("app/dyn.py", "import importlib\nimportlib.import_module('x')\n")
    assert repo.query("find", "nobody_calls_me")["dynamic_use_exists"] is True


def test_find_takes_a_dotted_name_by_its_last_part(shared):
    data = shared.query("find", "app.core.total")
    assert data["searched"] == "total" and names_at(data, "definition") == ["app/core.py:5"]


def test_find_reads_other_languages(repo):
    repo.write("a.go", "package a\n\nfunc Add() {}\n\nfunc B() { Add() }\n// Add is here\n")
    data = repo.query("find", "Add", "a.go")
    assert names_at(data, "definition") == ["a.go:3"] and names_at(data, "call") == ["a.go:5"] and names_at(data, "comment") == ["a.go:6"]


def test_find_never_prints_a_credential(repo):
    repo.write("app/conf.py", f'total_key = "x"\ntotal = "{TOKEN}"\n')
    done = repo.occam("query", "find", "total")
    assert TOKEN not in done.stdout and "withheld" in done.stdout


def test_find_treats_regex_characters_literally(repo):
    repo.write("app/odd.py", "x = 'a.b'\ny = 'aXb'\n")
    assert repo.query("find", "a.b")["searched"] == "b"
    assert repo.query("grep", "a\\.b", "app/odd.py")["total"] == 1

# ---------------------------------------------------------------- grep

def test_grep_knows_code_from_comments_and_strings(repo):
    repo.write("app/mixed.py", 'needle = 1  # needle\nx = "needle"\n')
    assert [row["kind"] for row in repo.query("grep", "needle", "app/mixed.py", "--in", "code")["rows"]] == ["code"]
    assert [row["where"] for row in repo.query("grep", "needle", "app/mixed.py", "--in", "string")["rows"]] == ["app/mixed.py:2"]
    assert repo.query("grep", "needle", "app/mixed.py")["total"] == 2


def test_grep_can_limit_by_language(shared):
    assert all(row["path"].endswith((".sh",)) for row in shared.query("grep", "echo", "--lang", "shell")["rows"])
    assert shared.query("grep", "echo", "--lang", "python")["total"] == 0


def test_grep_case_insensitive(shared):
    assert shared.query("grep", "LEDGER", "-i")["total"] >= 1
    assert shared.query("grep", "LEDGER")["total"] == 0


def test_a_bad_expression_is_an_error(shared):
    done = shared.occam("query", "grep", "(")
    assert done.returncode == 2 and "valid expression" in done.stdout


def test_output_is_bounded(shared):
    data = shared.query("grep", "def", "--top", "2")
    assert len(data["rows"]) == 2 and data["total"] > 2
    assert "Raise --top" in shared.text("grep", "def", "--top", "2")

# ---------------------------------------------------------------- functions

def test_functions_rank_by_each_measure(repo):
    long_body = "".join(f"    x{i} = {i}\n" for i in range(30))
    repo.write("app/big.py", f"def long_one():\n{long_body}\n\ndef tangled(a, b, c, d):\n    if a and b or c:\n        if d:\n            return [x for x in a if x]\n    return 0\n")
    assert repo.query("functions", "--sort", "lines", "--top", "1")["rows"][0]["name"] == "long_one"
    assert repo.query("functions", "--sort", "complexity", "--top", "1")["rows"][0]["name"] == "tangled"
    assert repo.query("functions", "--sort", "params", "--top", "1")["rows"][0]["name"] == "tangled"


def test_functions_leave_tests_out_unless_asked(shared):
    assert "test_total" not in [row["name"] for row in shared.query("functions", "--top", "100")["rows"]]
    assert "test_total" in [row["name"] for row in shared.query("functions", "--top", "100", "--include-tests")["rows"]]


def test_functions_read_braced_languages(repo):
    repo.write("a.go", "package a\n\nfunc Big(x int) int {\n\tif x > 1 {\n\t\treturn 1\n\t}\n\treturn 2\n}\n")
    rows = repo.query("functions", "a.go")["rows"]
    assert rows[0]["name"] == "Big" and rows[0]["complexity"] == 2 and rows[0]["params"] == 1


def test_a_scoped_functions_query_doesnt_read_the_rest(repo, monkeypatch):
    repo.write("elsewhere/bad.py", "def (:\n")
    assert repo.query("functions", "app")["unparsed"] == 0

# ---------------------------------------------------------------- api

def test_api_lists_public_names_by_convention(shared):
    names = [row["name"] for row in shared.query("api", "app/core.py")["rows"]]
    assert names == ["total", "Ledger", "Ledger.post"]


def test_api_honors_dunder_all(repo):
    repo.write("app/pub.py", '__all__ = ["keep"]\n\n\ndef keep():\n    pass\n\n\ndef drop():\n    pass\n')
    assert [row["name"] for row in repo.query("api", "app/pub.py")["rows"]] == ["keep"]


def test_api_counts_modules(shared):
    data = shared.query("api", "app/core.py", "app/lazy_part.py")
    assert data["modules"] == 2 and data["total"] == 4


def test_api_flags_a_changed_signature_in_another_language(repo):
    repo.write("a.go", "package a\n\nfunc Add(x int) int { return x }\n")
    repo.commit()
    repo.write("a.go", "package a\n\nfunc Add(x, y int) int { return x }\n")
    assert repo.query("api", "--base", "HEAD")["changed"][0]["breaking"] == ["signature text changed"]


def test_api_leaves_tests_and_private_modules_out(repo):
    repo.write("app/_inner.py", "def hidden():\n    pass\n")
    names = [row["where"] for row in repo.query("api", "--top", "100")["rows"]]
    assert not [name for name in names if name.startswith(("tests/", "app/_inner"))]


def test_api_reads_other_languages(repo):
    repo.write("a.go", "package a\n\nfunc Add(x int) int { return x }\n\nfunc hidden() {}\n\ntype Thing struct{}\n")
    repo.write("b.ts", "export function run(a: string): void {}\nfunction hidden() {}\nexport class Box {}\n")
    repo.write("c.rs", "pub fn go() {}\nfn hidden() {}\npub(crate) fn inner() {}\n")
    assert [row["name"] for row in repo.query("api", "a.go")["rows"]] == ["Add", "Thing"]
    assert [row["name"] for row in repo.query("api", "b.ts")["rows"]] == ["run", "Box"]
    assert [row["name"] for row in repo.query("api", "c.rs")["rows"]] == ["go"]


@pytest.mark.parametrize("before, after, reason", [
    ("def f(a, b):\n    pass\n", "def f(a):\n    pass\n", "parameter removed or renamed: b"),
    ("def f(a):\n    pass\n", "def f(renamed):\n    pass\n", "parameter removed or renamed: a"),
    ("def f(a):\n    pass\n", "def f(a, b):\n    pass\n", "new required parameter: b"),
    ("def f(a=1):\n    pass\n", "def f(a):\n    pass\n", "default removed: a"),
    ("def f(a, b):\n    pass\n", "def f(b, a):\n    pass\n", "positional parameters reordered"),
    ("def f(a):\n    pass\n", "def f(*, a):\n    pass\n", "positional parameter became keyword-only"),
    ("def f(*args):\n    pass\n", "def f():\n    pass\n", "*args removed"),
    ("def f(**kw):\n    pass\n", "def f():\n    pass\n", "**kwargs removed"),
])
def test_api_names_what_can_break_a_caller(repo, before, after, reason):
    repo.write("app/mod.py", before)
    repo.commit()
    repo.write("app/mod.py", after)
    changed = repo.query("api", "--base", "HEAD")["changed"]
    assert [row["name"] for row in changed] == ["f"] and reason in changed[0]["breaking"]


@pytest.mark.parametrize("before, after, said", [
    ("def f(a, retries=3):\n    pass\n", "def f(a, retries=0):\n    pass\n", ["default of retries changed from 3 to 0"]),
    ("def f(a, *, strict=False):\n    pass\n", "def f(a, *, strict=True):\n    pass\n", ["default of strict changed from False to True"]),
    # The same value, and a name whose value can't be read here, aren't reported.
    ("def f(a, timeout=30):\n    pass\n", "def f(a, timeout=30.0):\n    pass\n", []),
    ("def f(a, timeout=30):\n    pass\n", "def f(a, timeout=TIMEOUT):\n    pass\n", []),
])
def test_api_names_a_changed_default_apart_from_what_breaks(repo, before, after, said):
    repo.write("app/mod.py", before)
    repo.commit()
    repo.write("app/mod.py", after)
    changed = repo.query("api", "--base", "HEAD")["changed"]
    assert [row["defaults"] for row in changed] == [said] and changed[0]["breaking"] == []


def test_api_ignores_a_signature_only_reflowed(repo):
    repo.write("src/core.ts", "export function total(a: number, b: number): number {\n  return a + b;\n}\n")
    repo.commit()
    repo.write("src/core.ts", "export function total(\n  a: number,\n  b: number,\n): number {\n  return a + b;\n}\n")
    data = repo.query("api", "--base", "HEAD")
    assert not [row for row in data["changed"] if row["breaking"]] and data["removed"] == []


def test_api_doesnt_call_a_compatible_change_breaking(repo):
    repo.write("app/mod.py", "def f(a):\n    pass\n")
    repo.commit()
    repo.write("app/mod.py", "def f(a, b=1, *, c=2):\n    pass\n\n\ndef g():\n    pass\n")
    data = repo.query("api", "--base", "HEAD")
    assert data["changed"][0]["breaking"] == [] and data["removed"] == [] and [row["name"] for row in data["added"]] == ["g"]


def test_api_reports_removed_names_and_deleted_modules(repo):
    repo.write("app/mod.py", "def f():\n    pass\n\n\ndef g():\n    pass\n")
    repo.write("app/gone.py", "def h():\n    pass\n")
    repo.commit()
    repo.write("app/mod.py", "def f():\n    pass\n")
    (repo.path / "app/gone.py").unlink()
    assert {row["name"] for row in repo.query("api", "--base", "HEAD")["removed"]} == {"g", "h"}


def test_api_follows_a_rename(repo):
    repo.write("app/mod.py", "def f(a):\n" + "    x = 1\n" * 30)
    repo.commit()
    repo.git("mv", "app/mod.py", "app/moved.py")
    data = repo.query("api", "--base", "HEAD")
    assert data["removed"] == [] and data["added"] == []


def test_api_with_a_bad_revision_is_an_error(shared):
    assert shared.occam("query", "api", "--base", "no-such-rev").returncode == 2

# ---------------------------------------------------------------- boundaries

def test_boundaries_list_what_a_file_touches(shared):
    rows = {row["path"]: row for row in shared.query("boundaries", "--top", "50")["files"]}
    assert set(rows["app/payments.py"]["kinds"]) >= {"money", "tenancy", "database", "subprocess", "http-out"}
    assert shared.query("boundaries", "--top", "1")["files"][0]["path"] == "app/payments.py"


def test_a_comment_isnt_a_boundary(shared):
    sites = shared.query("boundaries", "--kind", "http-in")["sites"]["http-in"]
    assert [row["where"] for row in sites] == ["web/server.py:1"]
    money = [row["where"] for row in shared.query("boundaries", "--kind", "money")["sites"]["money"]]
    assert "app/payments.py:11" not in money


def test_sql_inside_a_string_is_a_boundary(shared):
    assert "app/payments.py:6" in [row["where"] for row in shared.query("boundaries", "--kind", "database")["sites"]["database"]]


def test_an_unknown_boundary_kind_is_an_error_not_an_empty_answer(shared):
    done = shared.occam("query", "boundaries", "--kind", "monye")
    assert done.returncode == 2 and "money" in done.stdout


def test_boundaries_leave_tests_out_unless_asked(repo):
    repo.write("tests/test_pay.py", "def test_x():\n    assert refund(1)\n\n\ndef refund(x):\n    return x\n")
    paths = [row["path"] for row in repo.query("boundaries", "--top", "100")["files"]]
    assert "tests/test_pay.py" not in paths
    assert "tests/test_pay.py" in [row["path"] for row in repo.query("boundaries", "--top", "100", "--include-tests")["files"]]

# ---------------------------------------------------------------- history

@pytest.fixture
def busy(repo):
    for index in range(3):
        repo.write("app/core.py", CORE + f"\n# {index}\n")
        repo.write("app/api.py", API + f"\n# {index}\n")
        repo.commit(f"fix something {index}", author="Bea" if index else "Ann")
    repo.write("app/lonely.py", FILES["app/lonely.py"] + "\n# one\n")
    repo.commit("add a thing")
    return repo


def test_history_ranks_churn_and_counts_fixes(busy):
    rows = {row["path"]: row for row in busy.query("history")["files"]}
    assert rows["app/core.py"]["commits"] == 4 and rows["app/core.py"]["fix_commits"] == 3
    assert rows["app/lonely.py"]["commits"] == 2 and rows["app/lonely.py"]["fix_commits"] == 0


def test_history_names_real_commits(busy):
    newest = busy.git("rev-parse", "--short", "HEAD").strip()
    assert busy.query("history", "app/lonely.py")["recent"][0]["commit"] == newest


def test_history_says_how_few_people_hold_it(busy):
    data = busy.query("history")
    assert dict(data["authors"]) == {"Ann": 3, "Bea": 2} and data["bus_factor"] == 1


def test_history_of_one_file_shows_commits_and_what_changes_with_it(busy):
    data = busy.query("history", "app/core.py")
    assert data["is_file"] and data["recent"][0]["subject"] == "fix something 2"
    assert [row["path"] for row in data["changed_together"]][:1] == ["app/api.py"]


def test_history_of_a_folder_stays_in_it(busy):
    assert {row["path"] for row in busy.query("history", "tests")["files"]} <= {path for path in FILES if path.startswith("tests/")}


def test_history_can_limit_by_commits_and_says_so(busy):
    data = busy.query("history", "--commits", "2")
    assert data["commits_read"] == 2 and data["limit_reached"]
    assert "Raise --commits" in busy.text("history", "--commits", "2")


def test_history_can_limit_by_date(busy):
    assert busy.query("history", "--since", "2000-01-01")["commits_read"] == 5
    assert "No commits found" in busy.text("history", "--since", "2098-01-01")


def test_history_reads_codeowners(busy):
    busy.write(".github/CODEOWNERS", "* @all\n/app/ @backend\n*.md @docs\n")
    busy.commit("owners")
    data = busy.query("history", "app/core.py")
    assert data["owners"] == "@backend"
    rows = {row["path"]: row["owners"] for row in busy.query("history", "--top", "100")["files"]}
    assert rows[".github/CODEOWNERS"] == "@all"


def test_history_leaves_vendored_files_out(busy):
    assert not [row for row in busy.query("history", "--top", "100")["files"] if row["path"].startswith("vendor/")]


def test_history_outside_git_is_an_error(tmp_path):
    repo = make_repo(tmp_path / "r", tmp_path / "s", git=False)
    done = repo.occam("query", "history")
    assert done.returncode == 2 and "Not a git repository" in done.stdout


def test_history_says_a_shallow_clone_is_cut_short(busy, tmp_path):
    clone = tmp_path / "clone"
    subprocess.run([GIT, "clone", "-q", "--depth", "1", f"file://{busy.path}", str(clone)], check=True, env=busy.env)
    shallow = Repo(clone, tmp_path / "state2")
    assert shallow.query("history")["shallow"] is True
    assert "shallow clone" in shallow.text("history")


def test_a_commit_message_cant_leak_a_credential(repo):
    repo.write("x.py", "x = 1\n")
    repo.commit(f"rotate {TOKEN}")
    assert TOKEN not in repo.text("history", "x.py")

# ---------------------------------------------------------------- leaks

def test_leaks_finds_a_credential_deleted_from_the_tree_and_withholds_it(repo):
    repo.write("app/conf.py", f'KEY = "{TOKEN}"\n')
    repo.commit("add")
    repo.write("app/conf.py", "KEY = None\n")
    repo.commit("remove")
    data = repo.query("leaks")
    assert [row["path"] for row in data["rows"]] == ["app/conf.py"] and data["rows"][0]["in_tree_now"] is False
    assert TOKEN not in repo.text("leaks")


def test_leaks_skips_test_paths_and_placeholders(repo):
    repo.write("tests/fixture.py", f'KEY = "{TOKEN}"\n')
    repo.write("app/conf.py", 'password = "changeme"\n')
    repo.commit("add")
    assert repo.query("leaks")["rows"] == []


def test_leaks_says_when_it_stopped_short(repo):
    repo.write("x.py", "x = 1\n")
    repo.commit("more")
    assert repo.query("leaks", "--commits", "1")["limit_reached"] is True

# ---------------------------------------------------------------- commands

def test_commands_lists_what_the_repository_states(shared):
    data = shared.query("commands", "--top", "50")
    rows = [row for rows in data["kinds"].values() for row in rows]
    assert {"python -m build", "ruff check .", "pytest -q", "echo done"} <= {row["command"] for row in rows}
    assert [row["where"] for row in data["kinds"]["test"] if row["where"].startswith("README")] == ["README.md:4"]


def test_commands_doesnt_take_console_output_for_a_command(shared):
    assert "3 passed" not in shared.text("commands", "--top", "50")


def test_commands_names_each_tox_environment(repo):
    repo.write("tox.ini", "[testenv:py39]\ncommands = pytest -x\n")
    rows = [row for rows in repo.query("commands", "--top", "100")["kinds"].values() for row in rows]
    assert "tox -e py39" in [row["name"] for row in rows]


def test_commands_reads_package_json_and_tox_and_nox_and_just(repo):
    repo.write("package.json", '{"scripts": {"test": "jest", "lint": "eslint ."}}')
    repo.write("tox.ini", "[testenv:py39]\ncommands = pytest -x\n")
    repo.write("noxfile.py", "import nox\n\n@nox.session\ndef docs(session):\n    pass\n")
    repo.write("justfile", "serve:\n  python -m http.server\n")
    rows = [row for rows in repo.query("commands", "--top", "100")["kinds"].values() for row in rows]
    commands = {row["command"] for row in rows}
    assert {"jest", "eslint .", "pytest -x", "nox -s docs", "just serve"} <= commands


@pytest.mark.parametrize("content", ["{ not json", '{"scripts": 3}', "[1, 2]"])
def test_commands_survives_a_malformed_package_json(repo, content):
    repo.write("package.json", content)
    assert repo.occam("query", "commands").returncode == 0
    assert repo.occam("query", "entry").returncode == 0


def test_commands_says_how_many_it_left_out(repo):
    repo.write("Makefile", "".join(f"test{i}:\n\tpytest\n" for i in range(5)))
    total = repo.query("commands", "--top", "2")["kind_totals"]["test"]
    assert total >= 5
    assert f"and {total - 2} more" in repo.text("commands", "--top", "2")


def test_commands_infers_only_with_a_label(repo):
    repo.write("go.mod", "module x\n")
    rows = [row for rows in repo.query("commands", "--top", "100")["kinds"].values() for row in rows]
    assert [row["how"] for row in rows if row["command"] == "go test ./..."] == ["inferred from this manifest, not stated"]


def test_commands_runs_nothing(repo):
    marker = repo.path / "ran"
    repo.write("Makefile", f"test:\n\ttouch {marker}\n")
    repo.occam("query", "commands")
    assert not marker.exists()


def test_commands_withholds_a_credential(repo):
    repo.write("Makefile", f"deploy:\n\tcurl -H 'token: {TOKEN}' x\n")
    assert TOKEN not in repo.text("commands", "--top", "100")

# ---------------------------------------------------------------- entry

def test_entry_finds_each_kind(shared):
    data = shared.query("entry", "--top", "50")
    assert "tool.py:3" in [row["where"] for row in data["kinds"]["main"]]
    assert [row["what"] for row in data["kinds"]["script"]] == ['demo = "app.api:load"']
    assert ["GET /health"] == [row["what"] for row in data["kinds"]["http"]]
    assert "Dockerfile:2" in [row["where"] for row in data["kinds"]["container"]]


def test_entry_leaves_a_commented_route_and_tests_out(repo):
    repo.write("tests/test_routes.py", '@app.get("/in-a-test")\ndef t():\n    pass\n')
    routes = repo.query("entry", "--top", "50")["kinds"]["http"]
    assert [row["where"] for row in routes] == ["web/server.py:1"]


def test_entry_reads_package_bin_and_jobs_and_clis(repo):
    repo.write("package.json", '{"name": "x", "bin": {"xtool": "cli.js"}, "main": "index.js"}')
    repo.write("app/jobs.py", "@celery.task\ndef run():\n    pass\n")
    repo.write("app/cli.py", "import argparse\nparser = argparse.ArgumentParser()\n")
    kinds = repo.query("entry", "--top", "50")["kinds"]
    assert "xtool = cli.js" in [row["what"] for row in kinds["script"]] and "main index.js" in [row["what"] for row in kinds["main"]]
    assert [row["where"] for row in kinds["job"]] == ["app/jobs.py:1"] and "app/cli.py:2" in [row["where"] for row in kinds["cli"]]


def test_entry_with_nothing_says_where_to_look(tmp_path):
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.write("a.py", "x = 1\n")
    repo.git("init", "-q")
    assert "check the manifests" in repo.text("entry")

# ---------------------------------------------------------------- markers

def test_markers_count_each_kind(repo):
    repo.write("app/skip.py", "x = f()  # type: ignore\ny = g()  # noqa: E501\n")
    repo.write("tests/test_skip.py", "import pytest\n\n\n@pytest.mark.skip\ndef test_a():\n    assert 1\n")
    repo.write("tests/a.test.js", "it.only('x', () => {})\nit.skip('y', () => {})\n")
    repo.write("ci.yml", "continue-on-error: true\n")
    repo.write("x.sh", "#!/bin/sh\nset -e\nfoo || true\n")
    kinds = repo.query("markers")["kinds"]
    assert kinds["suppression"]["total"] == 2 and kinds["skipped-test"]["total"] == 2
    assert kinds["focused-test"]["total"] == 1 and kinds["hidden-check"]["total"] == 2


def test_markers_dont_count_documents_or_a_python_keyword(repo):
    repo.write("docs/guide.md", "Use `# noqa` and `pytest.mark.skip` and `|| true`.\n")
    repo.write("app/io.py", "import shutil\nshutil.rmtree('x', ignore_errors=True)\n")
    kinds = repo.query("markers")["kinds"]
    assert kinds["suppression"]["total"] == 0 and kinds["skipped-test"]["total"] == 0 and kinds["hidden-check"]["total"] == 0


def test_markers_can_ask_for_one_kind(shared):
    assert list(shared.query("markers", "--kind", "suppression")["kinds"]) == ["suppression"]
