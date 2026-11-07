"""What a first trial on a large Ruby repository got wrong: answers that looked sure, in a language the patterns weren't written for."""

from __future__ import annotations

import subprocess
import time

import pytest
from query_support import GIT, Repo, make_repo, python_repo

RUBY = '''class Ledger
  def self.[](key)
    @cache.delete(key)
    @args.delete("version")
  end

  def <=>(other)
    total <=> other.total
  end

  def installed?
    if ENV.fetch("HOME") && ready
      system("ls")
    elsif done
      Open3.capture2("ls")
    end
    FileUtils.rm_rf(path)
    File.write(path, "x")
    @src.skip(1)
    settings.fetch(:a)
  end

  def one_liner; 1; end
end
'''


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo", tmp_path / "state")


def test_a_ruby_instance_variable_isnt_a_route(repo):
    repo.write("lib/ledger.rb", RUBY)
    output = repo.text("entry")
    assert "lib/ledger.rb" not in output and "DELETE" not in output


def test_routes_still_show_in_each_framework(repo):
    repo.write("web/a.py", '@app.get("/py")\ndef f():\n    return 1\n')
    repo.write("web/b.rb", "get '/rb' do\n  1\nend\n")
    output = repo.text("entry")
    assert "GET /py" in output and "GET /rb" in output


def test_a_bin_folder_is_where_programs_start(repo):
    repo.write("bin/tool", "#!/bin/sh\nexit 0\n")
    assert "bin/tool" in repo.text("entry")


def test_a_boundary_isnt_a_word_inside_another_call(repo):
    repo.write("lib/ledger.rb", RUBY)
    repo.write("web/c.js", 'await fetch("/x")\nwindow.fetch("/y")\nprefetch("/z")\n')
    sites = {row["where"] for row in repo.query("boundaries", "--kind", "http-out", "--top", "100")["sites"]["http-out"]}
    assert {"web/c.js:1", "web/c.js:2"} <= sites and "web/c.js:3" not in sites
    assert not any(where.startswith("lib/ledger.rb") for where in sites)
    routes = repo.query("boundaries", "--kind", "http-in", "--top", "100")["sites"].get("http-in", [])
    assert not any(row["where"].startswith("lib/ledger.rb") for row in routes)


@pytest.mark.parametrize("kind, line", [("subprocess", 13), ("subprocess", 15), ("file-write", 17), ("file-write", 18), ("environment", 12)])
def test_boundaries_read_ruby(repo, kind, line):
    repo.write("lib/ledger.rb", RUBY)
    sites = {row["where"] for row in repo.query("boundaries", "--kind", kind, "--top", "100")["sites"].get(kind, [])}
    assert f"lib/ledger.rb:{line}" in sites


def test_boundaries_say_when_a_language_is_outside_what_they_know(tmp_path):
    repo = python_repo(tmp_path, {"a.lua": "os.execute('ls')\n", "b.lua": "x = 1\n", "c.py": "import os\nos.system('ls')\n"})
    assert "lua (2 files)" in repo.text("boundaries")


def test_markers_read_more_checkers_and_fewer_accidents(repo):
    repo.write("a.rb", "# converted to nanoseconds here\nx = 1 # nosec\n# rubocop:disable Style/Foo\n")
    repo.write("b.rb", "# typed: false\n")
    repo.write("spec/a_spec.rb", '@src.skip(1)\nxit "x" do\nend\nskip "why"\nit.skip("y")\n')
    output = repo.text("markers", "--top", "100")
    for expected in ("a.rb:2", "a.rb:3", "b.rb:1", "spec/a_spec.rb:2", "spec/a_spec.rb:4", "spec/a_spec.rb:5"):
        assert expected in output, expected
    for accident in ("a.rb:1", "spec/a_spec.rb:1"):
        assert accident not in output, accident


def test_a_directory_counts_commits_not_files_touched(tmp_path):
    repo = python_repo(tmp_path, {"lib/a.py": "x = 1\n", "lib/b.py": "x = 2\n", "lib/c.py": "x = 3\n", "other/d.py": "x = 4\n"})
    rows = {row["path"]: row["commits"] for row in repo.query("history")["directories"]}
    assert rows["lib"] == 1 and rows["other"] == 1


def test_automation_isnt_an_owner_or_a_hotspot(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n", "b.py": "x = 1\n"})
    for index, author in enumerate(("dependabot[bot]", "BrewTestBot", "renovate-bot")):
        repo.write("a.py", f"x = {index + 2}\n")
        repo.commit("bump", author=author)
    data = repo.query("history")
    assert data["commits_read"] == 4 and data["automation_commits"] == 3
    assert {row["path"]: row["commits"] for row in data["files"]}["a.py"] == 1
    assert [name for name, _ in data["authors"]] == ["Ann"]
    assert "automation" in repo.text("history")


def test_a_surname_ending_in_bot_is_a_person(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    repo.write("a.py", "x = 2\n")
    repo.commit("edit", author="Ann Talbot")
    assert "Ann Talbot" in [name for name, _ in repo.query("history")["authors"]]


def test_a_repository_only_automation_touches_still_answers(tmp_path):
    (tmp_path / "r").mkdir()
    repo = Repo(tmp_path / "r", tmp_path / "s")
    repo.write("a.py", "x = 1\n")
    repo.git("init", "-q")
    repo.commit("first", author="dependabot[bot]")
    data = repo.query("history")
    assert data["commits_read"] == 1 and [row["path"] for row in data["files"]] == ["a.py"]


def test_history_ranks_what_keeps_getting_fixed(tmp_path):
    repo = python_repo(tmp_path, {"quiet.py": "x = 1\n", "buggy.py": "x = 1\n", "busy.py": "x = 1\n"})
    for index in range(4):
        repo.write("busy.py", f"x = {index + 2}\n")
        repo.commit("add a feature")
    for index in range(2):
        repo.write("buggy.py", f"x = {index + 2}\n")
        repo.commit("fix the crash")
    data = repo.query("history")
    assert data["most_fixed"][0]["path"] == "buggy.py" and data["most_fixed"][0]["fix_commits"] == 2
    assert "Most fixed" in repo.text("history")


def test_find_knows_a_ruby_definition(tmp_path):
    repo = python_repo(tmp_path, {"a.rb": "class A\n  def installed?\n    true\n  end\n  def self.installed?\n  end\nend\n", "b.rb": "x.installed?\n"})
    rows = {row["where"]: row["role"] for group in repo.query("find", "installed?")["groups"].values() for row in group}
    assert rows["a.rb:2"] == "definition" and rows["a.rb:5"] == "definition" and rows["b.rb:1"] != "definition"


def test_outline_names_ruby_operators_and_counts_as_wc_does(tmp_path):
    repo = python_repo(tmp_path, {"lib/ledger.rb": RUBY})
    output = repo.text("outline", "lib/ledger.rb")
    assert "self.[]" in output and "<=>" in output and "installed?" in output
    assert f"({RUBY.count(chr(10))} lines, ruby)" in output


def test_functions_read_ruby_methods(tmp_path):
    repo = python_repo(tmp_path, {"lib/ledger.rb": RUBY})
    rows = {row["name"]: row for row in repo.query("functions")["rows"]}
    assert rows["installed?"]["lines"] == 11 and rows["installed?"]["complexity"] >= 3
    assert rows["one_liner"]["lines"] == 1 and rows["self.[]"]["lines"] == 4


def test_functions_say_what_they_cant_read(tmp_path):
    repo = python_repo(tmp_path, {"a.lua": "function f()\nend\n"})
    assert "lua" in repo.text("functions")


def test_graph_follows_ruby_requires(tmp_path):
    repo = python_repo(tmp_path, {"Library/lib/a.rb": 'require "b"\n', "Library/lib/b.rb": 'require_relative "c"\n', "Library/lib/c.rb": "X = 1\n",
                                  "Library/lib/d.rb": 'autoload :C, "c"\n', "spec/c_check_spec.rb": 'require "c"\n'})
    data = repo.query("impact", "Library/lib/c.rb")
    assert {"Library/lib/a.rb", "Library/lib/b.rb", "Library/lib/d.rb"} <= set(data["source"])
    assert "spec/c_check_spec.rb" in data["tests"]


def test_impact_leads_with_what_it_cant_trace(tmp_path):
    repo = python_repo(tmp_path, {"a.lua": "x = 1\n"})
    first = repo.text("impact", "a.lua").split("\n")[0]
    assert "unknown" in first and "0 other source files" not in first


# ---------------------------------------------------------------- what a trial on a large Python project got wrong

def test_markers_read_what_python_projects_write(repo):
    repo.write("a.py", "x = 1  # NOQA\ny = 2  # noqa: E501\n")
    repo.write("tests/test_a.py", "@skipUnlessDBFeature('x')\ndef test_a():\n    pass\n\n\ndef test_b(self):\n    self.skipTest('no')\n\n\n@expectedFailure\ndef test_c():\n    pass\n")
    repo.write("b.py", "Entry.objects.only('id')\nmodel.fit(x)\n")
    repo.write("web/c.test.js", "it.only('x', () => {})\nfit('y', () => {})\n")
    output = repo.text("markers", "--top", "100")
    for expected in ("a.py:1", "a.py:2", "tests/test_a.py:1", "tests/test_a.py:7", "tests/test_a.py:10", "web/c.test.js:1", "web/c.test.js:2"):
        assert expected in output, expected
    for accident in ("b.py:1", "b.py:2"):
        assert accident not in output, accident


def test_history_dates_are_when_a_commit_landed(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    repo.write("a.py", "x = 2\n")
    repo.git("add", "-A")
    env = {**repo.env, "GIT_AUTHOR_DATE": "2001-01-01T00:00:00", "GIT_COMMITTER_DATE": "2030-01-01T00:00:00"}
    subprocess.run([GIT, "commit", "-qm", "old patch landed late"], cwd=repo.path, env=env, check=True)
    data = repo.query("history")
    assert "2001" not in repo.text("history")
    assert data["newest"] > 1_800_000_000


def test_mostly_means_more_than_half(tmp_path):
    repo = python_repo(tmp_path, {"AUTHORS.txt": "a\n", "a.py": "x = 1\n"})
    for name in ("Bea", "Cy", "Di", "Ed"):
        repo.write("a.py", f"x = '{name}'\n")
        repo.commit("edit", author=name)
    rows = {row["path"]: row["top_author"] for row in repo.query("history")["files"]}
    assert rows["a.py"].startswith("most often")
    assert rows["AUTHORS.txt"].startswith("mostly")


def test_entry_leaves_tests_and_documents_out_and_finds_how_django_starts(repo):
    repo.write("tests/pkg/__main__.py", "x = 1\n")
    repo.write("docs/topics.txt", "    path('docs/', views.index)\n")
    repo.write("site/urls.py", "urlpatterns = [\n    path('real/', view),\n]\n")
    repo.write("site/wsgi.py", "application = 1\n")
    repo.write("site/management/commands/migrate.py", "class Command:\n    pass\n")
    repo.write("site/management/commands/__init__.py", "")
    output = repo.text("entry", "--top", "100")
    assert "tests/pkg/__main__.py" not in output and "docs/topics.txt" not in output
    for expected in ("site/urls.py", "site/wsgi.py", "site/management/commands/migrate.py"):
        assert expected in output, expected
    assert "site/management/commands/__init__.py" not in output


def test_commands_read_a_tox_command_on_the_next_line(tmp_path):
    repo = python_repo(tmp_path, {"tox.ini": "[testenv:py]\ncommands =\n    {envpython} runtests.py {posargs}\n\n[testenv:docs]\nallowlist_externals = make\n"})
    output = repo.text("commands")
    assert "{envpython} runtests.py" in output and "tox -e docs" in output
    assert not any(line.startswith("    [") for line in output.split("\n"))


def test_api_sees_a_new_parameter_past_where_a_signature_is_cut(tmp_path):
    long_list = ", ".join(f"parameter_number_{index}=None" for index in range(12))
    repo = python_repo(tmp_path, {"lib/engine.py": f"class Engine:\n    def __init__(self, {long_list}):\n        pass\n"})
    repo.write("lib/engine.py", f"class Engine:\n    def __init__(self, {long_list}, added_last=None):\n        pass\n")
    repo.commit("a new optional parameter")
    data = repo.query("api", "lib/engine.py", "--base", "HEAD~1")
    assert "Engine.__init__" in [row["name"] for row in data["changed"]]


def test_api_counts_only_the_paths_asked_about(tmp_path):
    repo = python_repo(tmp_path, {"lib/a.py": "def f():\n    pass\n", "other/b.py": "def g():\n    pass\n"})
    repo.write("lib/a.py", "def f(x=1):\n    pass\n")
    (repo.path / "other" / "b.py").unlink()
    repo.commit("both")
    data = repo.query("api", "lib/a.py", "--base", "HEAD~1")
    assert data["files_compared"] == 1 and not data["removed"]


def test_fetch_is_a_network_call_only_in_a_browser_language(repo):
    repo.write("a.py", "row = cursor.fetch(1)\nvalue = fetch(key)\n")
    repo.write("b.js", 'await fetch("/x")\n')
    sites = {row["where"] for row in repo.query("boundaries", "--kind", "http-out", "--top", "100")["sites"]["http-out"]}
    assert "b.js:1" in sites and not any(where.startswith("a.py") for where in sites)


def test_prose_in_a_document_isnt_a_subprocess(repo):
    repo.write("page.html", "<p>The system (or spawn) is here</p>\n")
    repo.write("a.py", "system = 1\nos.system('ls')\n")
    repo.write("b.rb", 'system "ls"\n')
    sites = {row["where"] for row in repo.query("boundaries", "--kind", "subprocess", "--top", "100")["sites"].get("subprocess", [])}
    assert "a.py:2" in sites and "b.rb:1" in sites and "a.py:1" not in sites and not any(where.startswith("page.html") for where in sites)


def test_mail_and_sockets_count_as_the_network(repo):
    repo.write("a.py", "import smtplib\nserver = smtplib.SMTP('x')\nraw = socket.socket()\n")
    sites = {row["where"] for row in repo.query("boundaries", "--kind", "http-out", "--top", "100")["sites"].get("http-out", [])}
    assert {"a.py:2", "a.py:3"} <= sites


def test_an_authors_file_isnt_high_consequence(tmp_path):
    repo = python_repo(tmp_path, {"AUTHORS": "a\n", "app/auth.py": "x = 1\n", "app/authentication/views.py": "x = 1\n"})
    flags = {row["path"]: row["high_consequence"] for row in repo.query("history")["files"]}
    assert flags["AUTHORS"] is False and flags["app/auth.py"] is True and flags["app/authentication/views.py"] is True


def test_a_decorator_can_name_its_path_with_a_variable(repo):
    repo.write("web/a.py", "@app.get(PATH)\ndef f():\n    return 1\n\n\n@app.route(path)\ndef g():\n    return 1\n")
    output = repo.text("entry")
    assert "web/a.py:1" in output and "web/a.py:6" in output


def test_a_ruby_call_quoting_its_argument_isnt_a_route_either(repo):
    repo.write("lib/a.rb", 'class A\n  def f\n    @args.delete("version")\n  end\nend\n')
    assert "lib/a.rb" not in repo.text("entry")
    assert not [row for row in repo.query("boundaries", "--kind", "http-in")["sites"].get("http-in", []) if row["where"].startswith("lib/a.rb")]


@pytest.mark.parametrize("line", ["this.skip()", "t.skip()", "it.concurrent.skip('x', f)", "describe.skip('x', f)"])
def test_every_test_runner_way_of_skipping_is_read(repo, line):
    repo.write("web/a.test.js", line + "\n")
    assert "web/a.test.js:1" in repo.text("markers", "--top", "100")


def test_tabs_in_a_line_stay_tabs(repo):
    repo.write("a.py", "needle_with_tab =\t1\n")
    assert "\\x09" not in repo.text("grep", "needle_with_tab")


@pytest.mark.parametrize("author, counted", [("GitHub Actions", False), ("dependabot", False), ("renovatebot", False), ("github-actions[bot]", False), ("Ben Bot", True), ("Ann Talbot", True)])
def test_who_counts_as_automation(tmp_path, author, counted):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    repo.write("a.py", "x = 2\n")
    repo.commit("edit", author=author)
    assert (author in [name for name, _ in repo.query("history")["authors"]]) is counted


def test_many_files_with_one_name_cant_make_ruby_requires_slow(tmp_path):
    files = {f"d{index}/same.rb": 'require "same"\n' for index in range(600)}
    repo = python_repo(tmp_path, files)
    start = time.monotonic()
    assert repo.query("graph")
    assert time.monotonic() - start < 120  # cubic took minutes at this size even on a quiet machine


def test_api_of_the_whole_repository_counts_deleted_modules(tmp_path):
    repo = python_repo(tmp_path, {"lib/a.py": "def f():\n    pass\n", "lib/b.py": "def g():\n    pass\n"})
    (repo.path / "lib" / "b.py").unlink()
    repo.commit("remove")
    assert "g" in [row["name"] for row in repo.query("api", ".", "--base", "HEAD~1")["removed"]]


def test_renovate_bot_is_automation(tmp_path):
    repo = python_repo(tmp_path, {"a.py": "x = 1\n"})
    repo.write("a.py", "x = 2\n")
    repo.commit("bump", author="Renovate Bot")
    assert "Renovate Bot" not in [name for name, _ in repo.query("history")["authors"]]


def test_markers_tell_a_skip_from_a_word_that_starts_like_one(repo):
    repo.write("lib/a.rb", "@skip_auth = true\n")
    repo.write("web/b.js", "this.skip(1)\n")
    repo.write("web/c.test.js", "test.concurrent.only('x', f)\nthis.skip()\n")
    output = repo.text("markers", "--top", "100")
    assert "lib/a.rb:1" not in output and "web/b.js:1" not in output
    assert "web/c.test.js:1" in output and "web/c.test.js:2" in output
