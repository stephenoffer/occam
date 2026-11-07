"""`occam query graph`, `impact` and `tests`: what reaches what, where a wrong answer costs most."""

from __future__ import annotations

import sys

import pytest
from query_support import CORE, FILES, make_repo, python_repo



@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo", tmp_path / "state")


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """A repository no test changes, so the read-only queries needn't each build one."""
    base = tmp_path_factory.mktemp("shared")
    return make_repo(base / "repo", base / "state")


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
    repo.write("a.lua", "x = 1\n")
    assert "aren't traced" in repo.text("graph", "a.lua")

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
    data = repo.query("impact", "--changed")
    assert data["gone"] == ["app/optional_part.py"] and data["not_code"] == []
    assert "Removed or renamed away" in repo.text("impact", "--changed")


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

# ---------------------------------------------------------------- what reaches what, where a wrong answer costs most

def test_conftest_reaches_the_tests_beside_it_and_isnt_itself_a_test_to_run(tmp_path):
    repo = python_repo(tmp_path, {"src/__init__.py": "", "src/x.py": "VALUE = 1\n", "tests/conftest.py": "from src.x import VALUE\n", "tests/test_a.py": "def test_a():\n    assert 1\n",
                                   "tests/deep/test_b.py": "def test_b():\n    assert 1\n", "other/test_c.py": "def test_c():\n    assert 1\n"})
    data = repo.query("impact", "src/x.py", "--top", "50")
    assert set(data["tests"]) == {"tests/test_a.py", "tests/deep/test_b.py"} and data["all_tests"] == 3
    assert set(repo.query("impact", "tests/conftest.py", "--top", "50")["tests"]) == {"tests/test_a.py", "tests/deep/test_b.py"}


def test_a_parent_package_is_reached_by_importing_something_inside_it(tmp_path):
    repo = python_repo(tmp_path, {"pkg/__init__.py": "A = 1\n", "pkg/sub/__init__.py": "B = 1\n", "pkg/sub/mod.py": "def f():\n    return 1\n", "tests/test_m.py": "from pkg.sub.mod import f\n\n\ndef test_f():\n    assert f()\n"})
    assert repo.query("impact", "pkg/__init__.py", "--top", "50")["tests"] == ["tests/test_m.py"]
    assert repo.query("impact", "pkg/sub/__init__.py", "--top", "50")["tests"] == ["tests/test_m.py"]
    assert repo.query("graph")["cycles_total"] == 0


def test_same_named_modules_are_told_apart_by_who_imports_them(tmp_path):
    repo = python_repo(tmp_path, {"svc1/utils.py": "A = 1\n", "svc2/utils.py": "B = 1\n", "svc2/test_u.py": "import utils\n\n\ndef test_u():\n    assert utils.B\n"})
    assert repo.query("impact", "svc1/utils.py")["tests"] == []
    assert repo.query("impact", "svc2/utils.py")["tests"] == ["svc2/test_u.py"]


def test_an_import_that_could_mean_several_files_counts_them_all_and_says_so(tmp_path):
    repo = python_repo(tmp_path, {"svc1/shared.py": "A = 1\n", "svc2/shared.py": "B = 1\n", "app/main.py": "import shared\n"})
    assert "app/main.py" in repo.query("graph", "svc1/shared.py")["imported_by"]
    assert "app/main.py" in repo.query("graph", "svc2/shared.py")["imported_by"]
    assert "could mean several" in repo.text("graph")


def test_a_renamed_or_deleted_module_finds_the_tests_still_naming_it(tmp_path):
    repo = python_repo(tmp_path, {"foo.py": "A = 1\n" * 20, "tests/test_foo_use.py": "import foo\n\n\ndef test_it():\n    assert foo.A\n"})
    repo.git("mv", "foo.py", "bar.py")
    data = repo.query("impact", "--changed", "--top", "50")
    assert data["gone"] == ["foo.py"] and data["tests_naming_what_went"] == ["tests/test_foo_use.py"] and "tests/test_foo_use.py" in data["tests"]
    assert "No test reaches" not in repo.text("impact", "--changed")


def test_a_code_change_and_its_test_count_once(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "A = 1\n", "tests/test_a.py": "import a\n\n\ndef test_a():\n    assert a.A\n"})
    repo.write("a.py", "A = 2\n")
    repo.write("tests/test_a.py", "import a\n\n\ndef test_a():\n    assert a.A == 2\n")
    data = repo.query("impact", "--changed")
    assert data["tests"] == ["tests/test_a.py"] and data["tests_total"] == 1


@pytest.mark.parametrize("first_lines", ["# Do not edit the fixtures below by hand.\n", 'print "python two"\n', "x = (\n"], ids=["looks-generated", "python-2", "doesnt-parse"])
@pytest.mark.parametrize("line", ["from a import A\n", "from a import (\n    A,\n)\n", "from a import A, \\\n    B\n", "import a\n"], ids=["plain", "parens", "backslash", "module"])
def test_a_file_the_scanner_cant_read_keeps_its_imports(tmp_path, first_lines, line):
    repo = python_repo(tmp_path, {"a.py": "A = 1\nB = 2\n", "tests/test_a.py": line + first_lines})
    assert repo.query("impact", "a.py")["tests"] == ["tests/test_a.py"]


@pytest.mark.parametrize("files, seed", [
    ({"src/pk/mod.py": "X = 1\n", "tests/test_d.py": "from pk.mod import X\n"}, "src/pk/mod.py"),
    ({"services/api/lib/util.py": "X = 1\n", "tests/test_d.py": "from lib.util import X\n"}, "services/api/lib/util.py"),
    ({"__init__.py": "", "app.py": "X = 1\n", "tests/__init__.py": "", "tests/test_d.py": "from .. import app\n"}, "app.py"),
    ({"helper.py": "X = 1\n", "test_top.py": "from . import helper\n"}, "helper.py"),
    ({"vendor/lib/v.py": "X = 1\n", "tests/test_v1.py": "from lib.v import X\n"}, "vendor/lib/v.py"),
    ({"pkg/__init__.py": "X = 1\n", "pkg/tests/__init__.py": "", "pkg/tests/test_own.py": "def test_own():\n    assert 1\n"}, "pkg/__init__.py"),
], ids=["namespace-package", "deep-namespace", "up-to-the-root", "at-the-root", "named-vendored", "package-own-tests"])
def test_tests_are_found_however_the_import_is_written(tmp_path, files, seed):
    repo = python_repo(tmp_path, files)
    assert repo.query("impact", seed)["tests_total"] == 1


def test_a_standard_library_name_isnt_a_local_module(tmp_path):
    repo = python_repo(tmp_path, {"foundation/email/utils.py": "X = 1\n", "tests/test_d.py": "from email.utils import parseaddr\n"})
    assert repo.query("impact", "foundation/email/utils.py")["tests"] == []


def test_a_source_file_too_large_to_read_is_named(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "A = 1\n", "big.py": "x = 1\n" * 300_000})
    assert "too large to read" in repo.text("graph") and "big.py" in repo.query("graph")["unread"]


def test_the_answer_doesnt_keep_a_failed_parse_from_another_python():
    from occam_tools import scan
    assert f"py{sys.version_info.major}.{sys.version_info.minor}" in scan._CACHE_SCHEMA


@pytest.mark.parametrize("name, content", [
    ("tests/test_c.py", "# TODO: someday test deploy.sh\ndef test_c():\n    assert 1\n"),
    ("tests/test_d.py", '"""Nothing to do with deploy.sh."""\n\n\ndef test_d():\n    assert 1\n'),
    ("tests/README.md", "deploy.sh is checked by hand, and no test runs it.\n"),
    ("testdata/sample.json", '{"script": "deploy.sh"}\n'),
], ids=["comment", "docstring", "readme", "data"])
def test_only_a_tests_code_counts_as_running_a_script(tmp_path, name, content):
    repo = python_repo(tmp_path, {"deploy.sh": "#!/bin/bash\nset -e\n", name: content})
    data = repo.query("impact", "deploy.sh")
    assert data["tests"] == [] and data["tests_total"] <= data["all_tests"]


def test_a_path_picks_between_same_named_scripts(tmp_path):
    repo = python_repo(tmp_path, {"a/run.sh": "#!/bin/bash\nset -e\n", "b/run.sh": "#!/bin/bash\nset -e\n", "tests/test_a.py": 'X = "a/run.sh"\n\n\ndef test_a():\n    assert X\n'})
    assert repo.query("impact", "a/run.sh")["tests"] == ["tests/test_a.py"]
    assert repo.query("impact", "b/run.sh")["tests"] == []


def test_a_test_reached_only_by_naming_a_script_is_labeled(shared):
    assert "tests/test_tool.py" in shared.query("impact", "tool.py", "--top", "50")["tests_by_script"]
    assert "name a script in their code" in shared.text("impact", "tool.py", "--top", "50")


def test_a_tiny_file_handling_something_serious_still_counts_as_unreached(tmp_path):
    repo = python_repo(tmp_path, {"auth.py": "def check_password():\n    return True\n", "other.py": "X = 1\n", "tests/test_o.py": "import other\n\n\ndef test_o():\n    assert other.X\n"})
    assert [row["path"] for row in repo.query("tests")["no_test_reaches"]] == ["auth.py"]


@pytest.mark.parametrize("files, source, target", [
    ({"go.mod": "module example.invalid/m\n", "util/u.go": "package util\n", "other/o.go": "package other\n", "cmd/main.go": 'package main\n\nimport "example.invalid/m/util"\n\nimport (\n\t"example.invalid/m/other"\n)\n'}, "cmd/main.go", "util/u.go"),
    ({"go.mod": "module example.invalid/m\n", "util/u.go": "package util\n", "other/o.go": "package other\n", "cmd/main.go": 'package main\n\nimport "example.invalid/m/util"\n\nimport (\n\t"example.invalid/m/other"\n)\n'}, "cmd/main.go", "other/o.go"),
    ({"src/com/foo/bar/A.java": "package com.foo.bar;\nclass A {}\n", "src/com/x/M.java": "package com.x;\nimport com.foo.bar.*;\nclass M {}\n"}, "src/com/x/M.java", "src/com/foo/bar/A.java"),
    ({"src/main/kotlin/net/Conn.kt": "package org.example.net\nclass Conn\n", "src/main/kotlin/App.kt": "package org.example\nimport org.example.net.Conn\n"}, "src/main/kotlin/App.kt", "src/main/kotlin/net/Conn.kt"),
    ({"lib/a.h": "int a(void);\n", "src/m.c": "#include <lib/a.h>\n"}, "src/m.c", "lib/a.h"),
])
def test_imports_each_language_writes_more_than_one_way(tmp_path, files, source, target):
    repo = python_repo(tmp_path, files)
    assert target in repo.query("graph", source)["imports"]


def test_a_system_header_isnt_a_local_one(tmp_path):
    repo = python_repo(tmp_path, {"src/string.h": "int s(void);\n", "src/m.c": "#include <string.h>\n"})
    assert repo.query("graph", "src/m.c")["imports"] == []


def test_rust_tests_inside_a_source_file_count(tmp_path):
    repo = python_repo(tmp_path, {"Cargo.toml": '[package]\nname = "x"\n', "src/lib.rs": "pub fn a() {}\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn it() {}\n}\n"})
    data = repo.query("impact", "src/lib.rs")
    assert data["tests"] == ["src/lib.rs"] and data["tests_in_place"] == ["src/lib.rs"]
    assert repo.query("tests")["no_test_reaches"] == []


def test_tab_indented_python_is_found_under_git_too(tmp_path):
    repo = python_repo(tmp_path, {"a.py": 'class A:\n\tpass\n\nif True:\n\tif __name__ == "__main__":\n\t\tpass\n', "urls.py": "urlpatterns = [\n\tpath('x', view),\n]\n"})
    kinds = repo.query("entry", "--top", "50")["kinds"]
    assert "a.py:5" in [row["where"] for row in kinds["main"]] and "urls.py:2" in [row["where"] for row in kinds["http"]]
