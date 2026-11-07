"""Answers an agent acts on: a wrong "0 names removed", "nothing refers to this" or "no test reaches this" leads it to delete or skip something. Each case here gave one."""

from __future__ import annotations

import subprocess
import sys

import pytest
from query_support import Repo, python_repo
from sh_support import BASHES, TOOL

from occam_tools import query_repo
from occam_tools.source import is_test_path


def committed(tmp_path, files: dict) -> Repo:
    return python_repo(tmp_path, files)


def removed_names(repo: Repo) -> set[str]:
    return {row["name"] for row in repo.query("api", "--base", "HEAD")["removed"]}


# ---------------------------------------------------------------- 1. api --base

def test_api_sees_every_removal_the_audit_found_in_one_commit(tmp_path):
    repo = committed(tmp_path, {
        "pkg/__init__.py": '__all__ = ["keep", "other"]\nfrom .core import keep, other\n',
        "pkg/core.py": "def keep():\n    pass\n\n\ndef other():\n    pass\n",
        "web/index.ts": "export { a, b } from './m'\nconst c = 1\nexport { c }\n",
        "web/m.ts": "export const a = 1\nexport const b = 2\n",
        "go/g.go": "package g\n\ntype A struct{}\ntype B struct{}\n\nfunc (a A) Get() {}\nfunc (b B) Get() {}\n\nconst Limit = 1\nvar Default = 2\n",
        "rs/lib.rs": "pub struct A;\npub struct B;\n\nimpl A {\n    pub fn new() -> A { A }\n}\n\nimpl B {\n    pub fn new() -> B { B }\n}\n",
        "J.java": "public class J {\n    public void run(int a) {}\n    public void run(String b) {}\n}\n",
        "r.rb": "def hello\nend\n\ndef stays\nend\n",
    })
    repo.write("pkg/__init__.py", '__all__ = ["keep"]\nfrom .core import keep\n')
    repo.write("web/index.ts", "export { a } from './m'\n")
    repo.write("go/g.go", "package g\n\ntype A struct{}\ntype B struct{}\n\nfunc (b B) Get() {}\n")
    repo.write("rs/lib.rs", "pub struct A;\npub struct B;\n\nimpl B {\n    pub fn new() -> B { B }\n}\n")
    repo.write("J.java", "public class J {\n    public void run(int a) {}\n}\n")
    repo.write("r.rb", "def stays\nend\n")
    names = removed_names(repo)
    assert {"other", "b", "c", "A.Get", "Limit", "Default", "A::new", "hello"} <= names
    assert "B.Get" not in names and "B::new" not in names and "keep" not in names and "a" not in names
    assert [name for name in names if name.startswith("J.run")] == ["J.run(String b)"]
    assert "6 public modules changed. 0 names removed" not in repo.text("api", "--base", "HEAD")


def test_api_doesnt_call_an_ordinary_import_public(tmp_path):
    repo = committed(tmp_path, {"app/mod.py": "from os import path\nfrom .core import helper\n\n\ndef f():\n    return helper(path)\n"})
    repo.write("app/mod.py", "def f():\n    return 1\n")
    assert removed_names(repo) == set()


def test_api_reads_python_constants_and_an_explicit_reexport(tmp_path):
    repo = committed(tmp_path, {"app/mod.py": "from a import b as b\nLIMIT = 1\n_HIDDEN = 2\n\n\nclass K:\n    size: int = 1\n"})
    repo.write("app/mod.py", "class K:\n    pass\n")
    assert removed_names(repo) == {"b", "LIMIT", "K.size"}


def test_api_reads_a_package_init_with_no_all(tmp_path):
    repo = committed(tmp_path, {"pkg/__init__.py": "from .core import a\nfrom pkg.other import b\nfrom os import path\n"})
    repo.write("pkg/__init__.py", "from os import path\n")
    assert removed_names(repo) == {"a", "b"}


def test_api_counts_a_star_export_as_a_line_of_its_own(tmp_path):
    repo = committed(tmp_path, {"web/i.ts": "export * from './m'\nexport * as n from './n'\nexport default 1\n", "pkg/__init__.py": "from .core import *\n"})
    repo.write("web/i.ts", "export const z = 1\n")
    repo.write("pkg/__init__.py", "x = 1\n")
    assert removed_names(repo) == {"* from ./m", "n", "default", "* from .core"}


def test_api_keeps_a_changed_overload_a_change_and_not_a_removal(tmp_path):
    repo = committed(tmp_path, {"J.java": "public class J {\n    public void run(int a) {}\n    public void run(String b) {}\n}\n"})
    repo.write("J.java", "public class J {\n    public void run(int a) {}\n    public void run(String b, int c) {}\n}\n")
    data = repo.query("api", "--base", "HEAD")
    assert data["removed"] == [] and [row["name"] for row in data["changed"]] == ["J.run"]


def test_api_tells_methods_of_two_types_apart_in_other_languages(tmp_path):
    repo = committed(tmp_path, {
        "K.kt": "package a\n\nclass A {\n    fun get() {\n        val local = 1\n    }\n}\n\nclass B {\n    fun get() {}\n}\n",
        "C.cs": "public class A {\n    public void Run() {}\n}\n\npublic class B {\n    public void Run() {}\n}\n",
        "t.ts": "export class A {\n  run(a: string): void {\n    helper(a);\n  }\n  private hid() {}\n}\n\nexport class B {\n  run(): void {}\n}\n",
    })
    repo.write("K.kt", "package a\n\nclass A {\n}\n\nclass B {\n    fun get() {}\n}\n")
    repo.write("C.cs", "public class A {\n}\n\npublic class B {\n    public void Run() {}\n}\n")
    repo.write("t.ts", "export class A {\n}\n\nexport class B {\n  run(): void {}\n}\n")
    assert removed_names(repo) == {"A.get", "A.Run", "A.run"}


def test_api_reads_go_blocks_rust_traits_and_reexports_and_ruby_classes(tmp_path):
    repo = committed(tmp_path, {
        "g.go": "package g\n\nconst (\n\tLimit = 1\n\thidden = 2\n)\n\ntype (\n\tThing struct {\n\t\tField int\n\t}\n)\n",
        "lib.rs": "pub trait T {\n    fn must(&self);\n}\n\npub use crate::a::{b, c as d};\npub(crate) fn inner() {}\n",
        "m.rb": "class Box\n  LIMIT = 1\n  attr_reader :size\n\n  def run(a)\n  end\n\n  def self.make\n  end\n\n  private\n\n  def hid\n  end\nend\n",
    })
    repo.write("g.go", "package g\n")
    repo.write("lib.rs", "pub fn other() {}\n")
    repo.write("m.rb", "class Other\nend\n")
    assert removed_names(repo) == {"Limit", "Thing", "T", "T::must", "b", "d", "Box", "Box::LIMIT", "Box#size", "Box#run", "Box.make"}


def test_api_says_what_it_cant_read_instead_of_a_clean_count(tmp_path):
    repo = committed(tmp_path, {"a.swift": "public func gone() {}\n", "p.php": "<?php function gone() {}\n", "bad.py": "def f():\n    pass\n", "README.md": "x\n", "tests/test_a.py": "def test_a():\n    pass\n"})
    repo.write("a.swift", "public func other() {}\n")
    repo.write("p.php", "<?php function other() {}\n")
    repo.write("bad.py", "def (((:\n")
    repo.write("README.md", "y\n")
    repo.write("tests/test_a.py", "def test_b():\n    pass\n")
    output = repo.text("api", "--base", "HEAD")
    assert output.startswith("Against HEAD: 0 public modules changed. 0 names removed")
    assert "Not written for php (1 file), swift (1 file)" in output and "Couldn't parse or read 1 changed files" in output and "bad.py" in output
    assert "1 changed code files are tests, scripts or underscore modules" in output and "struct fields" in output


def test_a_file_that_stops_parsing_isnt_every_name_removed(tmp_path):
    repo = committed(tmp_path, {"app/mod.py": "def f():\n    pass\n"})
    repo.write("app/mod.py", "def (((:\n")
    data = repo.query("api", "--base", "HEAD")
    assert data["removed"] == [] and data["unread"] == ["app/mod.py"] and data["files_compared"] == 0


def test_api_says_when_all_is_built_at_runtime(tmp_path):
    repo = committed(tmp_path, {"app/mod.py": '__all__ = ["a"] + other.__all__\n\n\ndef a():\n    pass\n'})
    repo.write("app/mod.py", '__all__ = ["a"] + other.__all__\n\n\ndef a(x):\n    pass\n')
    assert "`__all__` is built at runtime in app/mod.py" in repo.text("api", "--base", "HEAD")


def test_api_doesnt_print_a_credential_from_a_changed_signature(tmp_path):
    secret = "ghp_" + "a1B2" * 10
    repo = committed(tmp_path, {"app/mod.py": f'def f(a, token="{secret}"):\n    pass\n'})
    repo.write("app/mod.py", f'def f(a, b, token="{secret}"):\n    pass\n')
    output = repo.text("api", "--base", "HEAD")
    assert secret not in output and "withheld" in output


# ---------------------------------------------------------------- 2. impact and tests

def dependents(repo: Repo, path: str) -> set[str]:
    return set(repo.query("impact", path)["source"])


def test_go_same_package_files_link_by_the_names_they_use(tmp_path):
    repo = committed(tmp_path, {"go.mod": "module m\n", "main.go": "package main\n\nfunc main() {\n\thelper()\n}\n", "util.go": "package main\n\nfunc helper() {}\n", "other.go": "package main\n\nfunc unrelated() {}\n"})
    assert dependents(repo, "util.go") == {"main.go"}
    assert dependents(repo, "other.go") == set(), "a file that says none of its names isn't a dependent"


def test_go_links_through_methods_constants_and_blocks(tmp_path):
    repo = committed(tmp_path, {"go.mod": "module m\n", "a.go": "package p\n\nfunc use() int {\n\treturn thing.Get() + Limit + other\n}\n",
                                "b.go": "package p\n\nfunc (x T) Get() int { return 1 }\n", "c.go": "package p\n\nconst Limit = 1\n", "d.go": "package p\n\nvar (\n\tother = 1\n)\n"})
    assert set(repo.query("graph", "a.go")["imports"]) == {"b.go", "c.go", "d.go"}


def test_go_links_dont_cross_comments_strings_packages_or_a_files_own_names(tmp_path):
    repo = committed(tmp_path, {"go.mod": "module m\n", "a.go": 'package p\n\n// helper in a comment\nvar s = "helper"\n',
                                "b.go": "package p\n\nfunc helper() {}\n",
                                "gen.go": "//go:build ignore\n\npackage main\n\nfunc main() {\n\thelper()\n}\n",
                                "x_linux.go": "//go:build linux\n\npackage p\n\nfunc open() {}\n", "x_darwin.go": "//go:build darwin\n\npackage p\n\nfunc open() {}\n",
                                "e.go": "package p\n\nfunc die(err error) string {\n\treturn err.Error()\n}\n", "f.go": "package p\n\ntype E struct{}\n\nfunc (e E) Error() string { return \"\" }\n"})
    assert dependents(repo, "b.go") == set()
    assert dependents(repo, "x_linux.go") == set() and dependents(repo, "x_darwin.go") == set()
    assert dependents(repo, "f.go") == set(), "`err.Error()` is on every error, so it says nothing about who implements it"


def test_go_code_doesnt_depend_on_what_a_test_file_declares(tmp_path):
    repo = committed(tmp_path, {"go.mod": "module m\n", "a.go": "package p\n\nfunc use() {\n\tfixture()\n}\n", "helpers_test.go": "package p\n\nfunc fixture() {}\n", "a_test.go": "package p\n\nfunc TestA() {\n\tfixture()\n}\n"})
    data = repo.query("impact", "helpers_test.go")
    assert data["source"] == [] and data["tests"][:2] == ["helpers_test.go", "a_test.go"]


def test_files_of_one_package_using_each_other_arent_an_import_cycle(tmp_path):
    repo = committed(tmp_path, {"go.mod": "module m\n", "a.go": "package p\n\nfunc A() {\n\tB()\n}\n", "b.go": "package p\n\nfunc B() {\n\tA()\n}\n",
                                "p/Alpha.java": "package p;\n\nclass Alpha { Beta b; }\n", "p/Beta.java": "package p;\n\nclass Beta { Alpha a; }\n"})
    data = repo.query("graph")
    assert data["cycles_total"] == 0 and data["edges"] == 4
    assert repo.query("graph", "a.go")["cycle"] is None and repo.query("graph", "a.go")["imported_by"] == ["b.go"]


def test_kotlin_import_of_a_top_level_function_reaches_the_file_that_declares_it(tmp_path):
    repo = committed(tmp_path, {"com/foo/Utils.kt": "package com.foo\n\nfun helper() {}\n", "com/foo/Other.kt": "package com.foo\n\nfun unrelated() {}\n", "app/Main.kt": "package app\n\nimport com.foo.helper\n\nfun main() {\n    helper()\n}\n"})
    assert dependents(repo, "com/foo/Utils.kt") == {"app/Main.kt"}
    assert dependents(repo, "com/foo/Other.kt") == set()


def test_kotlin_same_package_top_level_names_link(tmp_path):
    repo = committed(tmp_path, {"p/Utils.kt": "package p\n\nfun helper() {}\n\nprivate fun hidden() {}\n", "p/Main.kt": "package p\n\nfun main() {\n    helper()\n}\n", "p/Third.kt": "package p\n\nfun hidden() {}\n\nfun x() {\n    hidden()\n}\n"})
    assert dependents(repo, "p/Utils.kt") == {"p/Main.kt"}


def test_an_import_naming_nothing_in_the_package_links_to_nothing(tmp_path):
    repo = committed(tmp_path, {"com/foo/Utils.java": "package com.foo;\n\nclass Utils {}\n", "app/Main.java": "package app;\n\nimport com.foo.Generated;\n\nclass Main {}\n"})
    assert dependents(repo, "com/foo/Utils.java") == set()


@pytest.mark.parametrize("line, reached", [
    ("use crate::{b::thing, c::other};", {"src/b.rs", "src/c.rs"}),
    ("use crate::{\n    b::{self, thing},\n    c::other as o,\n};", {"src/b.rs", "src/c.rs"}),
    ("fn f() { crate::b::thing(); }", {"src/b.rs"}),
    ("fn f() { let x = crate::c::other(1); crate::b::thing(); }", {"src/b.rs", "src/c.rs"}),
    ("use crate::b::*;", {"src/b.rs"}),
    ("// use crate::b::thing;\nfn f() {}", set()),
    ('fn f() { println!("crate::b::thing"); }', set()),
    ("pub(in crate::b) fn f() {}", set()),
])
def test_rust_use_trees_and_written_out_paths(tmp_path, line, reached):
    repo = committed(tmp_path, {"Cargo.toml": '[package]\nname = "x"\n', "src/lib.rs": "mod a;\nmod b;\nmod c;\n", "src/a.rs": line + "\n", "src/b.rs": "pub fn thing() {}\n", "src/c.rs": "pub fn other() {}\n"})
    assert set(repo.query("graph", "src/a.rs")["imports"]) == reached


def test_rust_super_of_super_and_an_inline_path_to_another_crate(tmp_path):
    repo = committed(tmp_path, {"Cargo.toml": '[package]\nname = "my-lib"\n', "src/lib.rs": "pub mod top;\npub mod n;\n", "src/top.rs": "pub fn t() {}\n", "src/n/mod.rs": "pub mod m;\n",
                                "src/n/m/mod.rs": "pub mod d;\n", "src/n/m/d.rs": "use super::super::super::top::t;\n", "demo/Cargo.toml": '[package]\nname = "demo"\n', "demo/src/main.rs": "fn main() { my_lib::top::t(); }\n"})
    assert "src/top.rs" in repo.query("graph", "src/n/m/d.rs")["imports"]
    assert "demo/src/main.rs" in repo.query("impact", "src/top.rs")["source"]


def test_the_caveat_says_where_a_link_is_a_guess(tmp_path):
    repo = committed(tmp_path, {"go.mod": "module m\n", "main.go": "package main\n\nfunc main() {\n\thelper()\n}\n", "util.go": "package main\n\nfunc helper() {}\n", "lib.rs": "pub fn f() {}\n", "a.py": "x = 1\n"})
    output = repo.text("impact", "util.go")
    assert "Read from text and syntax" in output and "linked by the names they share" in output and "what a macro expands to" in output
    assert "linked by the names they share" not in committed_python_only(tmp_path).text("impact", "a.py"), "only what's here is worth saying"


def committed_python_only(tmp_path) -> Repo:
    (tmp_path / "py").mkdir()
    return committed(tmp_path / "py", {"a.py": "x = 1\n"})


# ---------------------------------------------------------------- 3. what counts as a test

@pytest.mark.parametrize("path, expected", [
    ("app/tests.py", True), ("tests.py", True), ("app/views_tests.py", True), ("spec/a.rb", True), ("lib/user_spec.rb", True), ("a_tests.go", True), ("a_spec.ts", True),
    ("app/contests.py", False), ("app/models.py", False), ("app/attests.py", False), ("app/tests.json.txt", False), ("app/special.py", False), ("app/inspect.py", False),
])
def test_django_and_rspec_names_are_tests(path, expected):
    assert is_test_path(path) is expected


def test_django_tests_reach_the_models_they_import(tmp_path):
    repo = committed(tmp_path, {"app/__init__.py": "", "app/models.py": "class M:\n    pass\n", "app/tests.py": "from app.models import M\n\n\ndef test_m():\n    assert M()\n"})
    data = repo.query("tests", "app/models.py")
    assert data["tests"] == ["app/tests.py"]
    assert "app/tests.py" not in repo.query("impact", "app/models.py")["source"]


@pytest.mark.parametrize("name", ["app/views_tests.py", "lib/views_spec.rb"])
def test_a_test_named_after_a_file_with_no_import_counts(tmp_path, name):
    repo = committed(tmp_path, {"app/views.py": "x = 1\n", name: "y = 1\n"})
    assert name in repo.query("tests", "app/views.py")["tests"]


# ---------------------------------------------------------------- 4. left-out folders

def left_out_repo(tmp_path) -> Repo:
    return committed(tmp_path, {"lib/thing.py": "def unique_helper_fn():\n    return 1\n", "tools/build/run.py": "from lib.thing import unique_helper_fn\n\nunique_helper_fn()\n"})


def test_find_says_a_caller_is_in_a_left_out_folder(tmp_path):
    output = left_out_repo(tmp_path).text("find", "unique_helper_fn")
    assert "Nothing refers to this" in output and "left out" in output and "tools/build/run.py:3" in output


def test_find_in_a_plain_folder_says_so_too(tmp_path):
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.write("lib/thing.py", "def unique_helper_fn():\n    return 1\n")
    repo.write("tools/build/run.py", "unique_helper_fn()\n")
    repo.write("node_modules/x/y.py", "unique_helper_fn()\n")
    output = repo.text("find", "unique_helper_fn")
    assert "tools/build/run.py:1" in output and "node_modules" not in output


def test_find_says_folders_are_left_out_when_no_caller_is_there(tmp_path):
    output = committed(tmp_path, {"lib/thing.py": "def unique_helper_fn():\n    return 1\n"}).text("find", "unique_helper_fn")
    assert "Nothing refers to this" in output and "Folders named vendor" in output and "left-out files name it" not in output


def test_find_with_a_caller_stays_quiet_about_left_out_folders(tmp_path):
    output = committed(tmp_path, {"lib/thing.py": "def unique_helper_fn():\n    return 1\n", "lib/use.py": "from lib.thing import unique_helper_fn\n\nunique_helper_fn()\n"}).text("find", "unique_helper_fn")
    assert "Folders named vendor" not in output


def test_find_narrowed_to_a_path_says_only_that_was_searched(tmp_path):
    repo = committed(tmp_path, {"lib/thing.py": "def unique_helper_fn():\n    return 1\n", "other/use.py": "unique_helper_fn()\n"})
    assert "Only lib was searched" in repo.text("find", "unique_helper_fn", "lib")


def test_impact_says_a_dependent_is_in_a_left_out_folder(tmp_path):
    output = left_out_repo(tmp_path).text("impact", "lib/thing.py")
    assert "0 other source files" in output and "Folders named vendor" in output and "tools/build/run.py:1" in output


def test_tests_says_folders_are_left_out(tmp_path):
    repo = committed(tmp_path, {"lib/thing.py": "x = 1\n"})
    assert "Folders named vendor" in repo.text("tests", "lib/thing.py")


# ---------------------------------------------------------------- 5. direct dependents

def test_direct_dependents_are_everything_that_imports_the_file(tmp_path):
    repo = committed(tmp_path, {"a.py": "x = 1\n", "b.py": "import a\n", "c.py": "import a\n", "d.py": "import c\n"})
    data = repo.query("impact", "a.py")
    assert data["direct"] == ["b.py", "c.py"] and set(data["source"]) == {"b.py", "c.py", "d.py"}


def test_a_test_that_imports_the_file_and_names_a_script_is_still_direct(tmp_path):
    repo = committed(tmp_path, {"a.py": 'if __name__ == "__main__":\n    pass\n', "run_me.py": 'if __name__ == "__main__":\n    pass\n', "tests/test_a.py": 'import a\n\nSCRIPT = "run_me.py"\n'})
    assert "tests/test_a.py" in repo.query("impact", "a.py")["direct"]


# ---------------------------------------------------------------- 6. CODEOWNERS

@pytest.mark.parametrize("pattern, path, expected", [
    ("docs/", "docs/a.md", True), ("docs/", "docs/sub/a.md", True), ("docs/", "x/docs/a.md", True), ("docs/", "docsy/a.md", False),
    ("apps/", "x/apps/a.js", True), ("apps/", "apps/a.js", True), ("apps/", "apps", False),
    ("/docs/", "docs/a.md", True), ("/docs/", "x/docs/a.md", False),
    ("src/*", "src/a.py", True), ("src/*", "src/d/a.py", False), ("src/*", "x/src/a.py", False),
    ("src/**", "src/d/a.py", True), ("src/**", "src/a.py", True), ("src/**", "src", False),
    ("/src/foo", "src/foobar.py", False), ("/src/foo", "src/foo", True), ("/src/foo", "src/foo/a.py", True),
    ("/docs/*", "docs/a.md", True), ("/docs/*", "docs/sub/a.md", False),
    ("*.md", "a.md", True), ("*.md", "x/y/a.md", True), ("*.md", "a.mdx", False), ("*", "x/y/a.md", True),
    ("**/logs", "logs", True), ("**/logs", "a/b/logs/c.txt", True), ("**/logs", "a/blogs/c.txt", False),
    ("a/**/b", "a/b", True), ("a/**/b", "a/x/y/b", True), ("a/**/b", "ax/b", False),
    ("apps/github", "apps/github/a.py", True), ("apps/github", "x/apps/github/a.py", False),
    ("/*", "a.py", True), ("/*", "x/a.py", False),
    ("a?c.py", "abc.py", True), ("a?c.py", "a/c.py", False),
    ("a.py", "axpy", False), ("[ab].py", "a.py", False), ("!a.py", "a.py", False), ("***", "a.py", False), ("/", "a.py", False),
])
def test_codeowners_patterns_match_as_github_says(pattern, path, expected):
    assert query_repo._owner_match(pattern, path) is expected


def test_the_last_matching_line_wins_even_when_it_names_nobody(tmp_path):
    (tmp_path / "CODEOWNERS").write_text("* @all\n/apps/ @octo\n/apps/github\n/apps/special @doc  # a note\n")
    assert query_repo.codeowners(tmp_path, "apps/x.py") == "@octo"
    assert query_repo.codeowners(tmp_path, "apps/github/x.py") is None
    assert query_repo.codeowners(tmp_path, "apps/special/x.py") == "@doc"
    assert query_repo.codeowners(tmp_path, "other.py") == "@all"


def test_a_hostile_codeowners_pattern_cant_take_long():
    import time
    started = time.monotonic()
    for pattern in ("*a" * 11 + "b", "/".join(["**"] * 20) + "/z", "*a" * 400):
        query_repo._owner_match(pattern, "a" * 300 + "/" + "a" * 300)
    assert time.monotonic() - started < 5


# ---------------------------------------------------------------- 7. what's a definition

def roles(repo: Repo, name: str) -> dict:
    return {row["where"]: role for role, rows in repo.query("find", name)["groups"].items() for row in rows}


@pytest.mark.parametrize("path, text", [
    ("a.c", "static int unused_fn(int a) {\n    return a;\n}\n"),
    ("a.c", "static int\nunused_fn(int a)\n{\n    return a;\n}\n"),
    ("a.h", "int unused_fn(int a);\n"),
    ("a.cpp", "void Box::unused_fn(int a) {\n}\n"),
    ("A.java", "class A {\n    public void unused_fn(int a) {\n    }\n}\n"),
    ("A.java", "class A {\n    @Override public List<String> unused_fn(int a) throws E {\n    }\n}\n"),
    ("A.java", "interface A {\n    void unused_fn(int a);\n}\n"),
    ("A.cs", "class A {\n    public int unused_fn() => 1;\n}\n"),
    ("a.ts", "class A {\n  unused_fn(a: string): void {\n  }\n}\n"),
    ("a.ts", "class A {\n  private async unused_fn(a) {\n  }\n}\n"),
    ("a.ts", "interface A {\n  unused_fn(a: string): void;\n}\n"),
    ("a.js", "class A {\n  unused_fn(a) {\n  }\n}\n"),
    ("a.ts", "class A {\n  unused_fn = (a) => a;\n}\n"),
    ("a.ts", "const o = {\n  unused_fn: (a) => a,\n};\n"),
    ("a.ts", "const o = {\n  unused_fn: function (a) {\n  },\n};\n"),
    ("a.kt", "fun unused_fn(a: Int) {\n}\n"),
    ("a.kt", "fun <T> String.unused_fn(a: T) {\n}\n"),
])
def test_a_definition_alone_says_nothing_refers_to_it(tmp_path, path, text):
    repo = committed(tmp_path, {path: text})
    data = repo.query("find", "unused_fn")
    assert data["references"] == 0 and list(data["groups"]) == ["definition"]
    assert "Nothing refers to this" in repo.text("find", "unused_fn")


@pytest.mark.parametrize("path, text", [
    ("a.c", "int main(void) {\n    called_fn(1);\n    return 0;\n}\n"),
    ("a.c", "int main(void) {\n    return called_fn(1);\n}\n"),
    ("a.c", "int main(void) {\n    int x = called_fn(1);\n}\n"),
    ("a.c", "int main(void) {\n    called_fn(a, b) {\n    }\n}\n"),
    ("a.c", "int main(void) {\n    if (x) called_fn(1);\n}\n"),
    ("a.c", "int main(void) {\n    else called_fn(1);\n}\n"),
    ("A.java", "class A {\n    void f() {\n        new called_fn(1) {\n        };\n    }\n}\n"),
    ("A.java", "class A {\n    void f() {\n        return called_fn(1);\n    }\n}\n"),
    ("A.java", "class A {\n    void f() {\n        this.called_fn(1);\n    }\n}\n"),
    ("A.java", "class A {\n    void f() {\n        called_fn(1);\n    }\n}\n"),
    ("a.ts", "called_fn(1);\n"),
    ("a.ts", "called_fn(() => {\n});\n"),
    ("a.ts", "const x = cond ? called_fn(1) : 2;\n"),
    ("a.ts", "await called_fn(1);\n"),
    ("A.java", "class A {\n    void f() {\n        assert called_fn(1);\n    }\n}\n"),
    ("a.groovy", "println called_fn(1)\n"),
    ("a.kt", "fun f() {\n    called_fn(1) {\n    }\n}\n"),
    ("a.swift", "func f() {\n    called_fn(1) {\n    }\n}\n"),
    ("a.go", "func f() {\n\tif called_fn(1) {\n\t}\n}\n"),
    ("a.rb", "called_fn(1) { |x| x }\n"),
])
def test_a_real_call_still_counts_as_one(tmp_path, path, text):
    data = committed(tmp_path, {path: text}).query("find", "called_fn")
    assert data["references"] >= 1 and "definition" not in data["groups"]


@pytest.mark.parametrize("line, name", [
    ("export const onlyArrow = (a) => a\n", "onlyArrow"),
    ("export const onlyArrow = async (a: string): Promise<string> => a\n", "onlyArrow"),
    ("const onlyArrow = a => a\n", "onlyArrow"),
    ("const onlyArrow: (a: number) => void = (a) => {\n  use(a);\n};\n", "onlyArrow"),
    ("export const onlyArrow = <T,>(a: T) => a\n", "onlyArrow"),
    ("const onlyArrow = function (a) {\n  return a;\n};\n", "onlyArrow"),
    ("class A {\n  onlyArrow = (a) => a;\n}\n", "onlyArrow"),
    ("const o = {\n  onlyArrow: (a) => a,\n};\n", "onlyArrow"),
])
def test_outline_and_functions_read_functions_held_in_a_name(tmp_path, line, name):
    repo = committed(tmp_path, {"a.ts": line})
    assert name in [row["name"] for row in repo.query("outline", "a.ts")["files"][0]["symbols"]]
    assert name in [row["name"] for row in repo.query("functions", "a.ts")["rows"]]


def test_a_braced_arrow_is_listed_once_with_its_size_and_branches(tmp_path):
    body = "export const f = (a, b) => {\n  if (a) {\n    return b;\n  }\n  return a ? b : 2;\n};\n\nconst g = (a) =>\n  a;\n"
    repo = committed(tmp_path, {"a.ts": body})
    rows = {row["name"]: row for row in repo.query("functions", "a.ts")["rows"]}
    assert [row["name"] for row in repo.query("outline", "a.ts")["files"][0]["symbols"]].count("f") == 1
    assert rows["f"]["lines"] == 6 and rows["f"]["complexity"] >= 2 and rows["f"]["params"] == 2


def test_things_that_only_look_like_function_values_arent_listed(tmp_path):
    repo = committed(tmp_path, {"a.ts": 'const n = 1\nconst s = "=>"\nconst t = cond ? a : b\nx = y => z\nconst u = (a)\nfoo(a => a)\nif (a === (b)) {}\n'})
    assert [row["name"] for row in repo.query("outline", "a.ts")["files"][0]["symbols"]] == ["x"]


def test_reading_function_values_stays_fast_on_a_hostile_file(tmp_path):
    import time
    repo = committed(tmp_path, {"a.ts": "const a = (b) => {\n" * 3000, "b.ts": "x = (" * 20000, "c.ts": "a: " * 20000 + "\n", "d.ts": "const f: " + "(a) => " * 5000 + "\n"})
    started = time.monotonic()
    repo.query("outline", "a.ts", "b.ts", "c.ts", "d.ts")
    assert time.monotonic() - started < 30


# ---------------------------------------------------------------- 8. occam.sh tests on a folder

def run_sh(path, *args, bash=BASHES[0]):
    return subprocess.run([bash, str(TOOL), *args], cwd=path, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize("git", [True, False], ids=["git", "plain"])
@pytest.mark.parametrize("target", ["src", ".", "src/"])
def test_occam_sh_expands_a_named_folder_as_occam_py_does(tmp_path, bash, git, target):
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.write("src/handler.py", "def h():\n    pass\n")
    repo.write("tests/test_x.py", "from handler import h\n")
    if git:
        repo.git("init", "-q")
        repo.commit()
    done = run_sh(repo.path, "tests", target, bash=bash)
    assert done.returncode == 0 and done.stdout.startswith("1 of 1 test files") and "tests/test_x.py" in done.stdout
    assert repo.query("tests", target)["tests_total"] == 1


def test_occam_sh_still_says_when_no_test_names_a_folders_files(tmp_path):
    repo = committed(tmp_path, {"src/handler.py": "x = 1\n", "other.py": "y = 1\n", "tests/test_x.py": "from other import y\n"})
    done = run_sh(repo.path, "tests", "src")
    assert done.returncode == 0 and done.stdout.startswith("0 of 1") and "No test names this" in done.stdout and "Folders named vendor" in done.stdout


def test_occam_sh_refuses_a_folder_with_no_code(tmp_path):
    repo = committed(tmp_path, {"data/a.txt": "x\n", "tests/test_x.py": "y = 1\n"})
    done = run_sh(repo.path, "tests", "data")
    assert done.returncode == 2 and "Nothing was checked" in done.stdout


def test_occam_sh_counts_the_new_test_names_like_occam_py(tmp_path):
    repo = committed(tmp_path, {"app/views.py": "x = 1\n", "app/views_tests.py": "y = 1\n", "app/tests.py": "z = 1\n", "lib/user.rb": "a = 1\n", "lib/user_spec.rb": "b = 1\n"})
    assert run_sh(repo.path, "tests").stdout.startswith("3 test files")
    assert "app/views_tests.py" in run_sh(repo.path, "tests", "app/views.py").stdout
    assert "lib/user_spec.rb" in run_sh(repo.path, "tests", "lib/user.rb").stdout


# ---------------------------------------------------------------- what roots a plain folder

@pytest.mark.parametrize("bash", BASHES)
def test_a_gitignore_above_a_plain_folder_doesnt_root_it(tmp_path, bash):
    parent = tmp_path / "home"
    (parent / "project" / "src").mkdir(parents=True)
    (parent / ".gitignore").write_text("*.log\n")
    (parent / "sibling.py").write_text("total = 1\n")
    (parent / "project" / "a.py").write_text("total = 2\n")
    state = {"OCCAM_STATE_DIR": str(tmp_path / "state"), "PYTHONDONTWRITEBYTECODE": "1"}
    env = {**__import__("os").environ, **state}
    sh = subprocess.run([bash, str(TOOL), "find", "total"], cwd=parent / "project", env=env, capture_output=True, text=True, timeout=60)
    assert sh.returncode == 0 and "1 files" in sh.stdout and "a.py" in sh.stdout and "sibling.py" not in sh.stdout
    from query_support import OCCAM
    py = subprocess.run([sys.executable, str(OCCAM), "query", "find", "total"], cwd=parent / "project", env=env, capture_output=True, text=True, timeout=60)
    assert "a.py" in py.stdout and "sibling.py" not in py.stdout
    # from below the plain folder, each roots where it started rather than at the parent's .gitignore
    sh = subprocess.run([bash, str(TOOL), "find", "total"], cwd=parent / "project" / "src", env=env, capture_output=True, text=True, timeout=60)
    py = subprocess.run([sys.executable, str(OCCAM), "query", "find", "total"], cwd=parent / "project" / "src", env=env, capture_output=True, text=True, timeout=60)
    assert "sibling.py" not in sh.stdout and "sibling.py" not in py.stdout
    # one in the starting folder does count, and a real marker above still does
    (parent / "project" / "src" / ".gitignore").write_text("*.log\n")
    (parent / "project" / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (parent / "project" / "src" / "b.py").write_text("total = 3\n")
    sh = subprocess.run([bash, str(TOOL), "find", "total"], cwd=parent / "project" / "src", env=env, capture_output=True, text=True, timeout=60)
    assert "b.py" in sh.stdout and "a.py" not in sh.stdout
    (parent / "project" / "src" / ".gitignore").unlink()
    sh = subprocess.run([bash, str(TOOL), "find", "total"], cwd=parent / "project" / "src", env=env, capture_output=True, text=True, timeout=60)
    assert "src/b.py" in sh.stdout and "a.py" in sh.stdout


# ---------------------------------------------------------------- 9. occam docs

def docs(repo: Repo, *args: str) -> subprocess.CompletedProcess:
    return repo.occam("docs", *args)


def plain_project(tmp_path, files: dict) -> Repo:
    repo = committed(tmp_path, files)
    repo.env = {**repo.env, "HOME": str(tmp_path / "no-home"), "OCCAM_HUMAN_VOICE": ""}
    return repo


def test_docs_exits_2_when_nothing_had_its_facts_checked(tmp_path):
    repo = plain_project(tmp_path, {"README.rst": "Call ``nope_here()``.\n"})
    done = docs(repo, "README.rst")
    assert done.returncode == 2 and "NOT CHECKED" in done.stdout and "No document had its facts checked" in done.stdout


def test_docs_with_one_document_checked_is_a_result(tmp_path):
    repo = plain_project(tmp_path, {"README.rst": "x\n", "a.md": "# A\n"})
    done = docs(repo, "README.rst", "a.md")
    assert done.returncode == 0 and "NOT CHECKED" in done.stdout


def test_docs_before_on_other_prose_compares_facts_so_it_counts(tmp_path):
    repo = plain_project(tmp_path, {"README.rst": "Rose 12.\n", "old.rst": "Rose 12.\n"})
    done = docs(repo, "README.rst", "--before", "old.rst")
    assert done.returncode == 0, done.stdout


@pytest.mark.parametrize("line", ["```foo``` is inline.", "```foo``` and ```bar```", "````foo```` is inline."])
def test_inline_code_opening_a_line_doesnt_stop_checking_the_rest(tmp_path, line):
    repo = plain_project(tmp_path, {"a.md": f"{line}\n\nSee `does/not/exist.py`.\n"})
    done = docs(repo, "a.md")
    assert done.returncode == 1 and "does/not/exist.py" in done.stdout


def test_a_real_fence_still_hides_what_is_in_it(tmp_path):
    repo = plain_project(tmp_path, {"a.md": "```text\nSee `does/not/exist.py`.\n```\n\n~~~ `odd` info\nSee `also/not/exist.py`.\n~~~\n"})
    done = docs(repo, "a.md")
    assert done.returncode == 0 and "exist.py" not in done.stdout


# ---------------------------------------------------------------- 10. smaller ones

@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize("shebang", ["#!/usr/bin/env sh", "#!/bin/dash", "#!/bin/sh", "#!/bin/ksh", "#!/usr/bin/env dash", "#!/bin/sh -e"])
def test_occam_sh_and_py_read_every_shell_shebang(tmp_path, bash, shebang):
    repo = committed(tmp_path, {"bin/tool": f"{shebang}\necho hi\n"})
    output = run_sh(repo.path, "shell", bash=bash).stdout
    assert output.startswith("1 shell scripts")
    assert repo.query("size")["languages"].get("shell")


@pytest.mark.parametrize("bash", BASHES)
@pytest.mark.parametrize("shebang", ["#!/usr/bin/env python3", "#!/usr/bin/env shellcheck", "#!/usr/local/shiny/run", "not a script"])
def test_other_shebangs_arent_taken_for_shell(tmp_path, bash, shebang):
    repo = committed(tmp_path, {"bin/tool": f"{shebang}\necho hi\n"})
    assert "bin/tool" not in run_sh(repo.path, "shell", bash=bash).stdout


@pytest.mark.parametrize("name", ["", "foo.", " ", "a.b."])
def test_find_with_no_name_is_a_bad_question(tmp_path, name):
    repo = committed(tmp_path, {"a.py": "foo = 1\n"})
    done = repo.occam("query", "find", name)
    assert done.returncode == 2 and "Nothing was checked" in done.stdout and "Nothing refers" not in done.stdout
    sh = run_sh(repo.path, "find", name)
    assert sh.returncode == 2 and "Nothing was checked" in sh.stdout


@pytest.mark.parametrize("manifest, entry", [
    ('{"name": "@w/lib", "exports": "./src/main.ts"}', "src/main.ts"),
    ('{"name": "@w/lib", "exports": {".": "./src/main.ts"}}', "src/main.ts"),
    ('{"name": "@w/lib", "exports": {".": {"types": "./src/main.d.ts", "import": "./src/main.ts"}}}', "src/main.ts"),
    ('{"name": "@w/lib", "exports": {"import": "./src/main.ts"}}', "src/main.ts"),
    ('{"name": "@w/lib", "main": "dist/index.js", "source": "src/main.ts"}', "src/main.ts"),
    ('{"name": "@w/lib", "exports": {".": "./dist/gone.js"}}', "src/index.ts"),
])
def test_a_workspace_package_resolves_through_what_it_declares(tmp_path, manifest, entry):
    repo = committed(tmp_path, {"packages/lib/package.json": manifest, "packages/lib/src/main.ts": "export const m = 1\n", "packages/lib/src/main.d.ts": "export const m: number\n", "packages/lib/src/index.ts": "export const i = 1\n", "app/use.ts": "import { m } from '@w/lib'\n"})
    assert repo.query("graph", "app/use.ts")["imports"] == [f"packages/lib/{entry}"]


def test_a_workspace_package_subpath_resolves_through_its_exports(tmp_path):
    repo = committed(tmp_path, {"packages/lib/package.json": '{"name": "@w/lib", "exports": {"./feature/*": "./src/features/*.ts"}}', "packages/lib/src/features/x.ts": "export const m = 1\n", "app/use.ts": "import { m } from '@w/lib/feature/x'\n"})
    assert repo.query("graph", "app/use.ts")["imports"] == ["packages/lib/src/features/x.ts"]


@pytest.mark.parametrize("path, expected", [("openapi_spec.py", False), ("api/openapi_spec.yaml", False), ("schema_spec.json", False), ("lib/user_spec.rb", True), ("a_spec.ts", True), ("run_tests.py", True)])
def test_a_spec_is_only_a_test_where_that_name_means_one(path, expected):
    """`run_tests.py` reads as a test too. It's a name no pattern shared with bash can separate, and it does test-running work anyway."""
    assert is_test_path(path) is expected


# ---------------------------------------------------------------- the same, for occam.py alone

@pytest.mark.parametrize("git", [True, False], ids=["git", "plain"])
@pytest.mark.parametrize("target", ["src", ".", "src/"])
def test_query_tests_expands_a_named_folder(tmp_path, git, target):
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.write("src/handler.py", "def h():\n    pass\n")
    repo.write("tests/test_x.py", "from handler import h\n")
    if git:
        repo.git("init", "-q")
        repo.commit()
    assert repo.query("tests", target)["tests_total"] == 1


@pytest.mark.parametrize("shebang", ["#!/usr/bin/env sh", "#!/bin/dash", "#!/bin/sh", "#!/bin/ksh", "#!/usr/bin/env dash", "#!/bin/sh -e"])
def test_query_reads_every_shell_shebang(tmp_path, shebang):
    repo = committed(tmp_path, {"bin/tool": f"{shebang}\necho hi\n"})
    assert repo.query("size")["languages"].get("shell")
