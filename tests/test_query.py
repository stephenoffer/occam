"""`occam query`, run for real through the command line against real repositories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugin" / "skills" / "occam" / "scripts"
OCCAM = SCRIPTS / "occam.py"
GIT = shutil.which("git")
TOKEN = "ghp_" + "a1B2" * 10
sys.path.insert(0, str(SCRIPTS))

from occam_tools import files as filesystem, query, query_code, toolrun  # noqa: E402

CORE = '''"""Core."""
import os


def total(a, b=1, *, cap=None):
    """Add."""
    if a > 0 and b > 0:
        return a + b
    return 0


class Ledger:
    def post(self, amount):
        return total(amount)

    def _hidden(self):
        return 1


def _private():
    return os.environ["A"]


if __name__ == "__main__":
    print(total(1))
'''
API = '''from app.core import total

try:
    from app import optional_part
except ImportError:
    optional_part = None


def load():
    from app import lazy_part
    return lazy_part.value() + total(2)


# total is mentioned in this comment
LABEL = "total"
TARGET = "app.core.total"
'''
FILES = {
    ".gitignore": "__pycache__/\n",
    "pyproject.toml": '[project]\nname = "demo"\n\n[project.scripts]\ndemo = "app.api:load"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n\n[tool.ruff]\nline-length = 100\n',
    "README.md": "# Demo\n\n```console\n$ pytest -q\n3 passed\n$ make build\n```\n\nThe word total appears here.\n",
    "Makefile": "build:\n\tpython -m build\n\ntest:\n\tpytest -q\n\n.PHONY: build\n",
    "Dockerfile": 'FROM python:3.12\nCMD ["python", "tool.py"]\n',
    ".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - run: ruff check .\n      - run: |\n          pytest -q\n          echo done\n",
    "app/__init__.py": "",
    "app/core.py": CORE,
    "app/api.py": API,
    "app/optional_part.py": "VALUE = 1\n",
    "app/lazy_part.py": "def value():\n    return 1\n",
    "app/lonely.py": "".join(f"def f{i}():\n    return {i}\n" for i in range(20)),
    "app/payments.py": 'import subprocess\nimport requests\n\n\ndef charge(amount, tenant_id):\n    db.execute("SELECT 1")\n    subprocess.run(["ls"])\n    return requests.post("https://x.invalid", timeout=1)\n\n\n# price is only mentioned here: stripe\n',
    "web/server.py": '@app.get("/health")\ndef health():\n    return 1\n\n\n# @app.post("/commented/out")\n',
    "tool.py": 'from app.api import load\n\nif __name__ == "__main__":\n    load()\n',
    "tests/__init__.py": "",
    "tests/test_core.py": "from app.core import total\n\n\ndef test_total():\n    assert total(1, 2) == 3\n",
    "tests/test_tool.py": 'import subprocess\n\n\ndef test_tool():\n    subprocess.run(["python", "tool.py"], check=True)\n',
    "tests/test_lazy_part.py": "def test_named_after_it():\n    assert True\n",
    "vendor/pkg/lib.py": "def total():\n    return 99\n",
    "dist/out.min.js": "function total(){}\n",
    "scripts/run.sh": '#!/bin/bash\nset -e\nsource ./lib.sh\necho hi\n',
    "scripts/lib.sh": "greet() {\n  echo hi\n}\n",
    "bin/noext": "#!/usr/bin/env python3\nprint(1)\n",
}


class Repo:
    def __init__(self, path: Path, state: Path) -> None:
        self.path = path
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

    def occam(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(OCCAM), *args], cwd=cwd or self.path, env=self.env, capture_output=True, text=True, timeout=120)

    def query(self, *args: str, cwd: Path | None = None) -> dict:
        done = self.occam("query", *args, "--format", "json", cwd=cwd)
        assert done.returncode == 0, done.stdout + done.stderr
        return json.loads(done.stdout)

    def text(self, *args: str) -> str:
        done = self.occam("query", *args)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout


def make_repo(path: Path, state: Path, git: bool = True) -> Repo:
    path.mkdir()
    repo = Repo(path, state)
    for name, content in FILES.items():
        repo.write(name, content)
    if git:
        repo.git("init", "-q")
        repo.commit("init")
    return repo


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
    assert data["vendored_or_generated_skipped"] == 2


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
    data = {"lines": 9_000_000, "files": 1, "other_files": 0, "vendored_or_generated_skipped": 0, "languages": {}, "depth": 1, "directories": [], "directories_total": 0, "subsystems": [], "largest_files": []}
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


# ---------------------------------------------------------------- graph

def test_graph_of_a_file_shows_both_directions(shared):
    data = shared.query("graph", "app/core.py")
    assert set(data["imported_by"]) >= {"app/api.py", "tests/test_core.py"} and "os" in data["external"]
    assert data["transitive_dependents"] >= data["imported_by_total"]


def test_graph_counts_optional_and_function_level_imports(shared):
    assert set(shared.query("graph", "app/api.py")["imports"]) >= {"app/optional_part.py", "app/lazy_part.py", "app/core.py"}


def test_graph_overview_finds_cycles_and_layers(repo):
    repo.write("a/x.py", "from b import y\n")
    repo.write("a/__init__.py", "")
    repo.write("b/y.py", "from a import x\n")
    repo.write("b/__init__.py", "")
    data = repo.query("graph")
    assert data["cycles_total"] >= 1 and any("a/x.py" in row["members"] for row in data["cycles"])
    assert ["a", "b"] in [list(pair) for pair in data["folder_loops"]]


def test_an_empty_init_doesnt_top_the_most_depended_on(shared):
    assert "app/__init__.py" not in [path for path, _ in shared.query("graph")["most_depended_on"]]


@pytest.mark.parametrize("files, source, target", [
    ({"pkg/a.ts": "import { b } from './b'\n", "pkg/b.ts": "export const b = 1\n"}, "pkg/a.ts", "pkg/b.ts"),
    ({"tsconfig.json": '{ // comment\n "compilerOptions": { "baseUrl": ".", "paths": { "@/*": ["src/*"] } } }', "src/a.ts": "import b from '@/lib/b'\n", "src/lib/b.ts": "export default 1\n"}, "src/a.ts", "src/lib/b.ts"),
    ({"packages/ui/package.json": '{"name": "@acme/ui"}', "packages/ui/src/index.ts": "export const a = 1\n", "apps/web/m.ts": "import { a } from '@acme/ui'\n"}, "apps/web/m.ts", "packages/ui/src/index.ts"),
    ({"go.mod": "module example.invalid/m\n", "lib/l.go": "package lib\n", "cmd/main.go": 'package main\n\nimport (\n\t"example.invalid/m/lib"\n)\n'}, "cmd/main.go", "lib/l.go"),
    ({"go.mod": "module example.invalid/m\n", "lib/l.go": "package lib\n", "lib/l_test.go": "package lib\n"}, "lib/l_test.go", "lib/l.go"),
    ({"src/com/a/Main.java": "package com.a;\nimport com.b.Util;\n", "src/com/b/Util.java": "package com.b;\n"}, "src/com/a/Main.java", "src/com/b/Util.java"),
    ({"src/com/a/One.java": "package com.a;\nclass One { Two t; }\n", "src/com/a/Two.java": "package com.a;\nclass Two {}\n"}, "src/com/a/One.java", "src/com/a/Two.java"),
    ({"src/m.c": '#include "util/u.h"\n', "src/util/u.h": "int u(void);\n"}, "src/m.c", "src/util/u.h"),
    ({"src/util/u.h": "int u(void);\n", "src/util/u.c": "int u(void) { return 1; }\n"}, "src/util/u.h", "src/util/u.c"),
    ({"src/m.c": '#include "util/u.h"\n', "include/util/u.h": "int u(void);\n"}, "src/m.c", "include/util/u.h"),
    ({"src/m.c": '#include "util/u.h"\n', "util/u.h": "int u(void);\n"}, "src/m.c", "util/u.h"),
    ({"Cargo.toml": '[package]\nname = "x"\n', "src/lib.rs": "mod util;\n", "src/util.rs": "pub fn a() {}\n"}, "src/lib.rs", "src/util.rs"),
    ({"Cargo.toml": '[package]\nname = "x"\n', "src/lib.rs": "use crate::util::a;\n", "src/util.rs": "pub fn a() {}\n"}, "src/lib.rs", "src/util.rs"),
    ({"run.sh": '#!/bin/bash\nsource ./lib/common.sh\n', "lib/common.sh": "a() { :; }\n"}, "run.sh", "lib/common.sh"),
    ({"run.sh": '#!/bin/bash\n. "$HERE/common.sh"\n', "lib/common.sh": "a() { :; }\n"}, "run.sh", "lib/common.sh"),
])
def test_graph_traces_each_language(tmp_path, files, source, target):
    repo = make_repo(tmp_path / "r", tmp_path / "s", git=False)
    for name in FILES:
        (repo.path / name).unlink()
    for name, content in files.items():
        repo.write(name, content)
    repo.git("init", "-q")
    repo.commit()
    assert target in repo.query("graph", source)["imports"]


def test_a_language_with_no_tracing_says_so(repo):
    repo.write("a.rb", "class A\nend\n")
    assert "aren't traced" in repo.text("graph", "a.rb")


# ---------------------------------------------------------------- impact

def test_impact_finds_dependents_and_the_tests_to_run(shared):
    data = shared.query("impact", "app/core.py", "--top", "50")
    assert {"app/api.py", "tool.py"} <= set(data["source"])
    assert "tests/test_core.py" in data["tests"]


def test_impact_reaches_a_test_that_runs_a_script_as_a_subprocess(shared):
    assert "tests/test_tool.py" in shared.query("impact", "app/core.py", "--top", "50")["tests"]


def test_impact_counts_a_test_named_after_the_file(shared):
    data = shared.query("impact", "app/lazy_part.py", "--top", "50")
    assert "tests/test_lazy_part.py" in data["tests_by_name"]


def test_impact_reaches_a_test_that_runs_a_shell_script_outside_a_scripts_folder(repo):
    repo.write("deploy.sh", "#!/bin/bash\nset -e\necho hi\n")
    repo.write("tests/test_deploy.py", 'import subprocess\n\n\ndef test_it():\n    subprocess.run(["bash", "deploy.sh"], check=True)\n')
    assert "tests/test_deploy.py" in repo.query("impact", "deploy.sh", "--top", "50")["tests"]


def test_a_longer_name_isnt_a_mention_of_a_script(repo):
    repo.write("tests/test_other.py", 'NAME = "pretool.py.bak"\n\n\ndef test_it():\n    assert NAME\n')
    assert "tests/test_other.py" not in repo.query("impact", "tool.py", "--top", "50")["tests"]


def test_impact_of_uncommitted_changes(repo):
    repo.write("app/core.py", CORE + "\n# changed\n")
    data = repo.query("impact", "--changed", "--top", "50")
    assert data["seeds"] == ["app/core.py"] and "tests/test_core.py" in data["tests"]


def test_impact_against_a_revision(repo):
    repo.write("app/core.py", CORE + "\n# changed\n")
    repo.commit()
    assert repo.query("impact", "--diff", "HEAD~1")["seeds"] == ["app/core.py"]


def test_impact_covers_a_deleted_file(repo):
    (repo.path / "app/optional_part.py").unlink()
    assert "app/optional_part.py" in repo.query("impact", "--changed")["seeds"]


def test_impact_of_nothing_says_so(shared):
    assert "no changes found" in shared.text("impact", "--changed")


def test_impact_says_config_cant_be_traced(repo):
    assert "pyproject.toml" in repo.query("impact", "pyproject.toml")["not_code"]
    assert "can reach anything" in repo.text("impact", "pyproject.toml")


def test_impact_finds_text_that_names_a_module_without_importing_it(repo):
    repo.write("config/plugins.yaml", "plugins:\n  - lonely\n")
    wheres = [row["where"] for row in repo.query("impact", "app/lonely.py", "--top", "50")["mentions"]]
    assert "config/plugins.yaml:2" in wheres


def test_a_longer_word_isnt_a_mention_of_a_module(repo):
    repo.write("config/plugins.yaml", "plugins:\n  - lonelyhearts\n")
    assert repo.query("impact", "app/lonely.py", "--top", "50")["mentions"] == []


def test_impact_says_when_no_test_reaches_a_file(shared):
    assert "Nothing here shows it's protected" in shared.text("impact", "app/lonely.py")


def test_impact_with_a_bad_revision_is_an_error(shared):
    assert shared.occam("query", "impact", "--diff", "no-such-rev").returncode == 2


# ---------------------------------------------------------------- tests

def test_tests_overview_finds_what_nothing_reaches(shared):
    data = shared.query("tests", "--top", "50")
    assert "app/lonely.py" in [row["path"] for row in data["no_test_reaches"]]
    assert "app/core.py" not in [row["path"] for row in data["no_test_reaches"]]
    assert data["test_files"] == 4 and data["test_functions"] == 3


def test_tests_overview_puts_consequence_first(repo):
    repo.write("app/zzz.py", "x = 1\n" * 500)
    repo.write("app/auth.py", "x = 1\n" * 20)
    rows = repo.query("tests", "--top", "50")["no_test_reaches"]
    assert [row["high_consequence"] for row in rows][:1] == [True] and rows[0]["path"] == "app/auth.py"


def test_tests_for_a_path(shared):
    assert "tests/test_core.py" in shared.query("tests", "app/core.py", "--top", "50")["tests"]
    assert shared.query("tests", "app/lonely.py")["tests"] == []


@pytest.mark.parametrize("name, content, rate", [
    ("coverage.xml", '<coverage><packages><package><classes><class name="x" filename="app/core.py" line-rate="0.25"></class></classes></package></packages></coverage>', 0.25),
    ("coverage.json", '{"files": {"app/core.py": {"summary": {"percent_covered": 25.0}}}}', 0.25),
    ("lcov.info", "SF:app/core.py\nLF:4\nLH:1\nend_of_record\n", 0.25),
    ("cover.out", "mode: set\napp/core.py:1.1,2.2 3 1\napp/core.py:3.1,4.2 9 0\n", 0.25),
])
def test_tests_overview_reads_a_coverage_report(repo, name, content, rate):
    repo.write(name, content)
    coverage = repo.query("tests")["coverage"]
    assert coverage["file"] == name and coverage["lowest"] == [{"path": "app/core.py", "rate": rate}]


def test_tests_overview_says_a_report_may_be_stale_and_when_theres_none(repo):
    assert repo.query("tests")["coverage"] is None and "No coverage report" in repo.text("tests")
    repo.write("lcov.info", "SF:app/core.py\nLF:4\nLH:1\nend_of_record\n")
    assert "may be stale" in repo.text("tests")


def test_a_malformed_coverage_report_is_ignored(repo):
    repo.write("coverage.json", "{ not json")
    assert repo.query("tests")["coverage"] is None


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


def test_markers_point_at_debt_for_deferred_work(shared):
    assert "occam debt" in shared.text("markers")


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
    assert query.safe_line("y" * 500).endswith("...")


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
