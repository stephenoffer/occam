"""What `occam gate` can only learn from the diff: did this change stay in scope?"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "skills" / "occam" / "scripts"))

from occam_tools import scan  # noqa: E402
from test_tools import Repo  # noqa: E402  (the real-git helper the other tool tests use)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    helper = Repo(path, tmp_path / "state")
    helper.git("init", "-q", "-b", "main")
    return helper


def rules_in(findings):
    return {finding["rule"] for finding in findings}


def out(done):
    return done.stdout + done.stderr


# ------------------------------------------------------------ shortcuts


def test_a_marked_shortcut_with_a_trigger_is_a_decision_and_not_a_placeholder():
    decided = scan.scan_text("app/a.py", "# shortcut: simplified version, replace when a second region ships\nX = 1\n")
    undecided = scan.scan_text("app/a.py", "# shortcut: simplified version\nX = 1\n")
    plain = scan.scan_text("app/a.py", "# simplified version, replace when a second region ships\nX = 1\n")
    assert "placeholder-comment" not in rules_in(decided)
    assert "placeholder-comment" in rules_in(undecided), "calling it a shortcut mustn't excuse a limit with no way out"
    assert "placeholder-comment" in rules_in(plain)


# ------------------------------------------------------------ gate: size

def test_gate_reports_the_size_of_the_change(repo):
    repo.write("app/a.py", "def f():\n    return 1\n\n\nprint(f())\n")
    repo.commit()
    repo.write("app/a.py", "def f():\n    return 2\n\n\nprint(f())\n\nprint(f())\n")
    repo.write("tests/test_new.py", "from app.a import f\n\n\ndef test_f():\n    assert f() == 2\n")
    assert "Size: +3 -1 lines of source, +5 -0 of tests." in repo.occam("gate").stdout


def test_gate_outside_git_does_not_claim_a_scope_check(tmp_path):
    (tmp_path / "a.py").write_text("X = 1\n")
    done = Repo(tmp_path, tmp_path / "state").occam("gate", "a.py")
    assert "Stayed in scope" not in done.stdout and "Size:" not in done.stdout


# ------------------------------------------------------------ gate: formatting churn

BODY = "".join(f"def f{i}(a, b):\n    return g(a, b)\n\n\n" for i in range(5))


def test_gate_notes_format_only_hunks(repo):
    repo.write("app/a.py", "VALUES = [\n    'one', 'two',\n    'three',\n]\n" + BODY)
    repo.commit()
    repo.write("app/a.py", 'VALUES = ["one", "two", "three"]\n' + BODY)
    assert "format-only" in repo.occam("gate").stdout


def test_a_string_changing_is_not_formatting(repo):
    repo.write("app/a.py", "A = 'x y'\nB = 'x y'\nC = 'x y'\nD = 'x y'\n")
    repo.commit()
    repo.write("app/a.py", "A = 'xy'\nB = 'xy'\nC = 'xy'\nD = 'xy'\n")
    assert "format-only" not in repo.occam("gate").stdout


def test_python_indentation_is_not_formatting(repo):
    repo.write("app/a.py", "def f(a):\n    for x in a:\n        g(x)\n        h(x)\n        i(x)\n        j(x)\n")
    repo.commit()
    repo.write("app/a.py", "def f(a):\n    for x in a:\n        g(x)\n    h(x)\n    i(x)\n    j(x)\n")
    assert "format-only" not in repo.occam("gate").stdout


def test_indenting_under_a_new_block_is_not_formatting(repo):
    repo.write("app/a.py", "def f(a):\n    g(a)\n    h(a)\n    i(a)\n    j(a)\n")
    repo.commit()
    repo.write("app/a.py", "def f(a):\n    if a:\n        g(a)\n        h(a)\n        i(a)\n        j(a)\n")
    assert "format-only" not in repo.occam("gate").stdout


def test_one_stray_reformatted_line_is_not_worth_a_note(repo):
    repo.write("app/a.py", "A = 'x'\nB = 2\n")
    repo.commit()
    repo.write("app/a.py", 'A = "x"\nB = 2\n')
    assert "format-only" not in repo.occam("gate").stdout


def test_indentation_only_counts_as_formatting_where_it_has_no_meaning(repo):
    repo.write("src/a.ts", "function f() {\n  g();\n  h();\n  i();\n}\n")
    repo.commit()
    repo.write("src/a.ts", "function f() {\n    g();\n    h();\n    i();\n}\n")
    assert "format-only" in repo.occam("gate").stdout


# ------------------------------------------------------------ gate: comments

def test_gate_notes_comments_removed_with_no_code_change(repo):
    repo.write("app/a.py", "# Retries live upstream: the gateway already backs off.\ndef f():\n    return g()\n")
    repo.commit()
    repo.write("app/a.py", "def f():\n    return g()\n")
    assert "comment-removed" in repo.occam("gate").stdout


def test_gate_notes_comments_reworded_with_no_code_change(repo):
    repo.write("src/a.ts", "// the gateway backs off\nconst x = 1;\n")
    repo.commit()
    repo.write("src/a.ts", "// handles the backoff logic\nconst x = 1;\n")
    assert "comment-removed" in repo.occam("gate").stdout


def test_a_comment_removed_with_its_code_is_fine(repo):
    repo.write("app/a.py", "def f():\n    # back off\n    sleep(1)\n    return 1\n")
    repo.commit()
    repo.write("app/a.py", "def f():\n    return 1\n")
    assert "comment-removed" not in repo.occam("gate").stdout


def test_finishing_a_todo_is_fine(repo):
    repo.write("app/a.py", "# TODO: add the header\nX = 1\n")
    repo.commit()
    repo.write("app/a.py", "X = 1\n")
    assert "comment-removed" not in repo.occam("gate").stdout


def test_a_shebang_is_not_a_comment_here(repo):
    repo.write("run.sh", "#!/bin/sh\necho hi\n")
    repo.commit()
    repo.write("run.sh", "#!/bin/bash\necho hi\n")
    assert "comment-removed" not in repo.occam("gate").stdout


# ------------------------------------------------------------ gate: orphans

def test_gate_finds_what_this_change_orphaned_in_an_unchanged_file(repo):
    repo.write("app/helpers.py", "def slugify_title(x):\n    return x.lower()\n")
    repo.write("app/view.py", "from app.helpers import slugify_title\n\n\ndef show(x):\n    return slugify_title(x)\n\n\nprint(show('a'))\n")
    repo.commit()
    repo.write("app/view.py", "def show(x):\n    return x\n\n\nprint(show('a'))\n")
    done = repo.occam("gate").stdout
    assert "orphaned-by-change" in done and "slugify_title has no references left" in done and "app/helpers.py" in done


def test_gate_leaves_code_that_was_already_dead(repo):
    repo.write("app/old.py", "def already_dead(x):\n    return x\n\n\nprint(1)\n")
    repo.write("app/view.py", "def show(x):\n    return x\n\n\nprint(show('a'))\n")
    repo.commit()
    repo.write("app/view.py", "def show(x):\n    return x + 1\n\n\nprint(show('a'))\n")
    assert "already_dead" not in repo.occam("gate").stdout


def test_moving_a_definition_does_not_count_as_orphaning_it(repo):
    repo.write("app/a.py", "def lonely(x):\n    return x\n\n\nprint(1)\n")
    repo.commit()
    repo.write("app/a.py", "print(1)\n\n\ndef lonely(x):\n    return x\n")
    assert "orphaned-by-change" not in repo.occam("gate").stdout


# ------------------------------------------------------------ gate: heavier than the file around it

PLAIN_FILE = "".join(f"def f{i}(a):\n    return g(a)\n\n\n" for i in range(20)) + "print(f0(1))\n"


def test_gate_notes_handlers_out_of_line_with_the_file(repo):
    repo.write("app/a.py", PLAIN_FILE)
    repo.commit()
    guarded = "def added(a):\n    try:\n        b = g(a)\n    except ValueError:\n        b = 0\n    try:\n        c = g(b)\n    except KeyError:\n        c = 1\n    try:\n        d = g(c)\n    except TypeError:\n        d = 2\n    return d\n\n\nprint(added(1))\n"
    repo.write("app/a.py", PLAIN_FILE + guarded)
    assert "handler-density" in repo.occam("gate").stdout


def test_handlers_are_fine_where_the_file_already_handles_things(repo):
    handled = "".join(f"def f{i}(a):\n    try:\n        return g(a)\n    except ValueError:\n        return {i}\n\n\n" for i in range(12)) + "print(f0(1))\n"
    repo.write("app/a.py", handled)
    repo.commit()
    guarded = "def added(a):\n    try:\n        b = g(a)\n    except ValueError:\n        b = 0\n    try:\n        c = g(b)\n    except KeyError:\n        c = 1\n    return c\n\n\nprint(added(1))\n"
    repo.write("app/a.py", handled + guarded)
    assert "handler-density" not in repo.occam("gate").stdout


def test_gate_notes_comments_out_of_line_with_the_file(repo):
    repo.write("app/a.py", PLAIN_FILE)
    repo.commit()
    noisy = "def added(a):\n    # take the value\n    b = g(a)\n    # add one\n    c = b + 1\n    # add two\n    d = c + 2\n    # return it\n    return d\n\n\nprint(added(1))\n"
    repo.write("app/a.py", PLAIN_FILE + noisy)
    assert "comment-density" in repo.occam("gate").stdout


def test_a_new_file_has_no_norm_to_compare_with(repo):
    repo.write("app/seed.py", "X = 1\n")
    repo.commit()
    repo.write("app/new.py", "# one\nA = 1\n# two\nB = 2\n# three\nC = 3\n# four\nD = 4\n# five\nE = 5\n")
    assert "comment-density" not in repo.occam("gate").stdout


def test_scope_notes_warn_and_do_not_block(repo):
    repo.write("app/a.py", "# Keep this: the gateway backs off.\nX = 1\n\n\nprint(X)\n")
    repo.commit()
    repo.write("app/a.py", "X = 1\n\n\nprint(X)\n")
    done = repo.occam("gate")
    assert "comment-removed" in done.stdout and done.returncode == 0
    assert repo.occam("gate", "--strict").returncode == 1


# ------------------------------------------------------------ unused-option can only speak for calls it saw

def test_unused_option_stays_quiet_when_a_file_could_not_be_read(tmp_path):
    (tmp_path / "net.py").write_text("def fetch(url, retries=3):\n    return url * retries\n")
    (tmp_path / "caller.py").write_text("from net import fetch\nprint(fetch('x'))\n")
    (tmp_path / "other.py").write_text("from net import fetch\nprint(fetch('x', retries=9)\n")  # missing a bracket, so its call to fetch can't be read
    visible = scan.filter_findings(scan.run_scan(tmp_path, use_cache=False).findings, "medium")
    assert "unused-option" not in rules_in(visible)
    assert "unparseable" in rules_in(visible)


# ------------------------------------------------------------ from the fresh review: these must never be called formatting

@pytest.mark.parametrize("name, before, after", [
    ("a.py", "A = ('x',)\nB = ('y',)\nC = ('z',)\nD = 1\n", "A = ('x')\nB = ('y')\nC = ('z')\nD = 1\n"),
    ("a.py", "def f(rows):\n    for r in rows:\n        g('a')\n        g('b')\n        g('c')\n", 'def f(rows):\n    for r in rows:\n        g("a")\n    g("b")\n    g("c")\n'),
    ("a.py", 'X = """hello big\nand more big\nand yet more\n"""\n', 'X = """hellobig\nandmorebig\nandyetmore\n"""\n'),
    ("a.ts", "const a = `x y`;\nconst b = `x y`;\nconst c = `x y`;\n", "const a = `xy`;\nconst b = `xy`;\nconst c = `xy`;\n"),
    ("run.sh", "echo '$HOME'\necho '$PATH'\necho '$USER'\n", 'echo "$HOME"\necho "$PATH"\necho "$USER"\n'),
    ("run.sh", "cp a b\ncp c d\ncp e f\n", "cp ab\ncp cd\ncp ef\n"),
    ("a.c", "char a = 'x';\nchar b = 'y';\nchar c = 'z';\n", 'char *a = "x";\nchar *b = "y";\nchar *c = "z";\n'),
    ("a.sql", "SELECT 'x';\nSELECT 'y';\nSELECT 'z';\n", 'SELECT "x";\nSELECT "y";\nSELECT "z";\n'),
    ("a.hs", "f x =\n  case x of\n    1 -> 2\n    _ -> 3\n", "f x =\n  case x of\n  1 -> 2\n  _ -> 3\n"),
])
def test_a_change_with_meaning_is_never_called_formatting(repo, name, before, after):
    repo.write(name, before)
    repo.commit()
    repo.write(name, after)
    assert "format-only" not in repo.occam("gate").stdout


def test_python_reformatting_is_formatting_when_the_syntax_tree_proves_it(repo):
    repo.write("a.py", "VALUES = [\n    'one', 'two',\n    'three',\n]\n\n\ndef f(a,\n      b):\n    return (a +\n            b)\n")
    repo.commit()
    repo.write("a.py", 'VALUES = ["one", "two", "three"]\n\n\ndef f(a, b):\n    return a + b\n')
    assert "format-only" in repo.occam("gate").stdout


def test_python_reformatting_beside_a_real_change_is_still_noticed(repo):
    repo.write("a.py", "VALUES = [\n    'one',\n    'two',\n]\n\n\ndef f(a):\n    return a\n")
    repo.commit()
    repo.write("a.py", 'VALUES = ["one", "two"]\n\n\ndef f(a):\n    return a + 1\n')
    assert "format-only" in repo.occam("gate").stdout


def test_a_template_literal_line_reindented_is_not_formatting(repo):
    repo.write("a.ts", "const a = `\n  one\n  two\n  three\n`;\n")
    repo.commit()
    repo.write("a.ts", "const a = `\n    one\n    two\n    three\n`;\n")
    assert "format-only" not in repo.occam("gate").stdout


# ------------------------------------------------------------ orphans: only when a real reference went

@pytest.mark.parametrize("removed_line", [
    "# parse_header goes first\n",
    "print('parse_header')\n",
    "sorted([1], parse_header=len)\n",
])
def test_a_mention_that_was_not_a_reference_does_not_make_an_orphan(repo, removed_line):
    repo.write("app/old.py", "def parse_header(x):\n    return x\n\n\nprint(1)\n")
    repo.write("app/view.py", removed_line + "print(2)\n")
    repo.commit()
    repo.write("app/view.py", "print(2)\n")
    assert "orphaned-by-change" not in repo.occam("gate").stdout


def test_short_names_are_not_judged_at_all(repo):
    repo.write("app/k.py", "class K:\n    pass\n\n\nprint(K(), K())\n")
    repo.write("app/view.py", "from app.k import K\nprint(K)\n")
    repo.commit()
    repo.write("app/view.py", "print(2)\n")
    assert "K lost" not in repo.occam("gate").stdout and "K has no references" not in repo.occam("gate").stdout


def test_an_entry_point_named_in_config_is_not_an_orphan(repo):
    repo.write("pyproject.toml", '[project]\nname = "x"\n[project.scripts]\nrun = "app.tool:run_tool"\n')
    repo.write("app/tool.py", "def run_tool():\n    return 1\n")
    repo.write("app/view.py", "from app.tool import run_tool\nprint(run_tool())\n")
    repo.commit()
    repo.write("app/view.py", "print(2)\n")
    assert "orphaned-by-change" not in repo.occam("gate").stdout


def test_a_method_can_be_orphaned_too(repo):
    repo.write("app/k.py", "class Klass:\n    def lonely_method(self):\n        return 1\n")
    repo.write("app/view.py", "from app.k import Klass\nprint(Klass().lonely_method())\n")
    repo.commit()
    repo.write("app/view.py", "from app.k import Klass\nprint(Klass())\n")
    done = repo.occam("gate").stdout
    assert "orphaned-by-change" in done and "lonely_method" in done


def test_deleting_the_only_caller_orphans_what_it_called(repo):
    repo.write("app/helpers.py", "def slugify_title(x):\n    return x.lower()\n")
    repo.write("app/view.py", "from app.helpers import slugify_title\nprint(slugify_title('a'))\n")
    repo.commit()
    (repo.path / "app/view.py").unlink()
    assert "orphaned-by-change" in repo.occam("gate").stdout


# ------------------------------------------------------------ --base means what this branch did

def test_base_compares_with_where_the_branch_forked(repo):
    repo.write("app/a.py", "X = 1\n")
    repo.write("app/gone.py", "Y = 1\n")
    repo.commit()
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("app/z.py", "Z = 1\nprint(Z)\n")
    repo.commit()
    repo.git("checkout", "-q", "-")
    repo.write("app/a.py", "# the base branch added this later\nX = 1\n")
    (repo.path / "app/gone.py").unlink()
    repo.commit()
    main = repo.git("rev-parse", "HEAD").strip()
    repo.git("checkout", "-q", "feature")
    done = repo.occam("gate", "--base", main).stdout
    assert "1 changed files, 0 deleted" in done
    assert "Size: +2 -0 lines of source" in done
    assert "comment-removed" not in done


# ------------------------------------------------------------ comments: what actually happened to them

def test_a_multiplication_operand_is_not_a_comment(repo):
    repo.write("a.ts", "const total = price\n  * quantity\n  * rate;\n")
    repo.commit()
    repo.write("a.ts", "const total = price\n  * rate;\n")
    assert "comment-removed" not in repo.occam("gate").stdout


def test_text_inside_a_string_is_not_a_comment(repo):
    repo.write("a.py", 'X = """\n# heading\nbody\n"""\n')
    repo.commit()
    repo.write("a.py", 'X = """\nbody\n"""\n')
    assert "comment-removed" not in repo.occam("gate").stdout


@pytest.mark.parametrize("before, after", [
    ("# keep this reason\nX = 1\nY = 2\n", "X = 1\n# keep this reason\nY = 2\n"),
    ("#keep this reason\nX = 1\n", "# keep this reason\nX = 1\n"),
])
def test_a_comment_moved_or_respaced_was_not_lost(repo, before, after):
    repo.write("a.py", before)
    repo.commit()
    repo.write("a.py", after)
    assert "comment-removed" not in repo.occam("gate").stdout


def test_a_trailing_comment_can_be_lost(repo):
    repo.write("a.py", "A = 1  # the gateway needs this\n")
    repo.commit()
    repo.write("a.py", "A = 1\n")
    assert "comment-removed" in repo.occam("gate").stdout


def test_inside_a_block_comment_counts(repo):
    repo.write("a.ts", "/*\nwhy this exists\nand who needs it\n*/\nconst x = 1;\n")
    repo.commit()
    repo.write("a.ts", "const x = 1;\n")
    assert "comment-removed" in repo.occam("gate").stdout


def test_ordinary_prose_with_a_marker_word_is_not_finished_work(repo):
    repo.write("a.py", "# hack the planet: the gateway needs this\nX = 1\n")
    repo.commit()
    repo.write("a.py", "X = 1\n")
    assert "comment-removed" in repo.occam("gate").stdout


def test_a_first_line_removal_has_a_real_line_number(repo):
    repo.write("a.py", "# the reason\nX = 1\n")
    repo.commit()
    repo.write("a.py", "X = 1\n")
    assert "a.py:0" not in repo.occam("gate").stdout


# ------------------------------------------------------------ density reads code, not text that looks like it

def test_comments_and_strings_do_not_count_as_handlers(repo):
    repo.write("a.ts", "".join(f"export const v{i} = {i};\n" for i in range(40)))
    repo.commit()
    added = "// catch up later\n// catch this next\nconst s = `\ncatch one\ncatch two\n`;\nconst a = 1;\nconst b = 2;\nconst c = 3;\nconst d = 4;\n"
    repo.write("a.ts", repo.path.joinpath("a.ts").read_text() + added)
    assert "handler-density" not in repo.occam("gate").stdout


def test_density_compares_a_renamed_file_with_its_old_self(repo):
    repo.write("app/old_name.py", PLAIN_FILE)
    repo.commit()
    repo.git("mv", "app/old_name.py", "app/new_name.py")
    noisy = "def added(a):\n    # take the value\n    b = g(a)\n    # add one\n    c = b + 1\n    # add two\n    d = c + 2\n    # return it\n    return d\n\n\nprint(added(1))\n"
    repo.write("app/new_name.py", PLAIN_FILE + noisy)
    assert "comment-density" in repo.occam("gate").stdout


# ------------------------------------------------------------ size counts what was read

def test_a_notebook_is_not_counted_as_source_lines(repo):
    book = '{"cells": [{"cell_type": "code", "source": ["x = 1\\n"], "metadata": {}, "outputs": [], "execution_count": null}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n'
    repo.write("a.ipynb", book)
    repo.commit()
    repo.write("a.ipynb", book.replace("x = 1", "x = 2"))
    assert "Size: +1 -1" not in repo.occam("gate").stdout


def test_no_size_line_when_nothing_read_changed(repo):
    repo.write("a.css", "a { color: red; }\n")
    repo.commit()
    repo.write("a.css", "a { color: blue; }\n")
    assert "Size:" not in repo.occam("gate").stdout


def test_an_inter_hunk_setting_cannot_confuse_the_parse(repo):
    repo.write("a.py", "A = 1\nB = 2\nC = 3\nD = 4\nE = 5\nF = 6\n")
    repo.write("b.py", "X = 1\n")
    repo.commit()
    repo.git("config", "diff.interHunkContext", "10")
    repo.write("a.py", "A = 9\nB = 2\nC = 3\nD = 4\nE = 5\nF = 9\n")
    repo.write("b.py", "X = 2\n")
    assert "Size: +3 -3 lines of source" in repo.occam("gate").stdout


# ------------------------------------------------------------ unused-option can't claim what it can't see

BASE_NET = {"app/net.py": "def fetch(url, retries=3):\n    return url * retries\n"}


def unused_option_fires(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return "unused-option" in rules_in(scan.run_scan(tmp_path, use_cache=False).findings)


@pytest.mark.parametrize("files", [
    {**BASE_NET, "app/a.py": "from app.net import fetch as get\nprint(get('x', retries=2))\nprint(get('y'))\n"},
    {**BASE_NET, "app/a.py": "from app.net import fetch\nprint(fetch('x'))\nprint(getattr(fetch, 'x', 1))\n"},
    {**BASE_NET, "app/a.py": "import app.net as m\nfrom app.net import fetch\nprint(fetch('x'))\nprint(getattr(m, 'fetch')('x', retries=2))\n"},
    {**BASE_NET, "app/a.py": "import app.net as m\nfrom app.net import fetch\nprint(fetch('x'))\nname = input()\nprint(getattr(m, name)('x', retries=2))\n"},
    {"app/net.py": "__all__ = ['fetch']\n\n\ndef fetch(url, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"},
    {"app/net.py": "class Client:\n    def __init__(self, url, timeout=3):\n        self.url = url\n        self.timeout = timeout\n\n    @classmethod\n    def make(cls, url):\n        return cls(url, timeout=1)\n", "app/a.py": "from app.net import Client\nprint(Client('x'))\n"},
    {"app/net.py": "class Client:\n    def __init__(self, url, timeout=3):\n        self.url = url\n        self.timeout = timeout\n\n    def copy(self):\n        return type(self)(self.url, timeout=1)\n", "app/a.py": "from app.net import Client\nprint(Client('x'))\n"},
    {"app/net.py": "class Client:\n    def __init__(self, url, timeout=3):\n        self.url = url\n        self.timeout = timeout\n\n    def copy(self):\n        return self.__class__(self.url, timeout=1)\n", "app/a.py": "from app.net import Client\nprint(Client('x'))\n"},
    {"app/net.py": "REG = []\n\n\ndef register(c):\n    REG.append(c)\n    return c\n\n\n@register\nclass Client:\n    def __init__(self, url, timeout=3):\n        self.url = url\n        self.timeout = timeout\n", "app/a.py": "from app.net import Client, REG\nprint(Client('x'), REG[0]('x', timeout=9))\n"},
    {"app/net.py": "class Client:\n    def __init__(self, url, timeout=3):\n        self.url = url\n", "app/a.py": "from app.net import Client\nprint(Client('x'))\nREG = {'c': Client}\nprint(REG['c']('y', timeout=9))\n"},
    {"app/net.py": "import functools\n\n\n@functools.lru_cache\ndef fetch(url, retries=3):\n    return url * retries\n", "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"},
    {"app/net.py": "class Base:\n    def go(self, x, y=1):\n        return x + y\n\n\nclass Sub(Base):\n    pass\n", "app/a.py": "from app.net import Sub\nprint(Sub().go(1))\n"},
    {"app/net.py": "def main(argv=None):\n    return argv\n", "app/a.py": "from app.net import main\nprint(main())\n"},
    {"app/net.py": "def fetch(url, retries=3):\n    return url\n", "app/other.py": "def fetch(url, retries=4):\n    return url\n", "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"},
    {"pyproject.toml": '[project]\nname = "lib"\n', **BASE_NET, "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"},
], ids=["import-alias", "value-use", "getattr-literal", "getattr-dynamic", "exported", "cls", "type-self", "dunder-class", "decorated-class", "class-as-value", "decorated", "class-family", "main", "ambiguous", "library"])
def test_unused_option_stays_silent_when_calls_cannot_all_be_seen(tmp_path, files):
    assert not unused_option_fires(tmp_path, files)


def test_unused_option_still_fires_when_every_call_is_visible(tmp_path):
    assert unused_option_fires(tmp_path, {**BASE_NET, "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n"})


def test_unused_option_says_what_it_read_rather_than_what_exists(tmp_path):
    (tmp_path / "net.py").write_text(BASE_NET["app/net.py"])
    (tmp_path / "a.py").write_text("from net import fetch\nprint(fetch('x'))\n")
    message = next(f["message"] for f in scan.run_scan(tmp_path, use_cache=False).findings if f["rule"] == "unused-option")
    assert "in this repository" not in message and "retries" in message


# ------------------------------------------------------------ ts-double-cast and prose

@pytest.mark.parametrize("code, fires", [
    ("const u = d as unknown as User;\n", True),
    ("const u = d as unknown as 'a';\n", True),
    ("const u = d as unknown as string;\n", True),
    ("const u = d as any as { a: 1 };\n", True),
    ("const el = <p>treat it as unknown as well</p>;\n", False),
])
def test_ts_double_cast_reads_a_type_after_it(code, fires):
    assert ("ts-double-cast" in rules_in(scan.scan_text("src/a.tsx", code))) is fires


# ------------------------------------------------------------ shortcuts only excuse themselves with a stated way out

@pytest.mark.parametrize("comment", [
    "# shortcut: placeholder that returns 0 if the input is empty",
    "# shortcut: placeholder, returns a hard-coded value over the wire",
    "# shortcut: simplified version, see #3",
    "# shortcut: simplified version, buffer is 2048 bytes",
    "# Shortcut: placeholder implementation when in doubt",
])
def test_a_limit_with_no_way_out_is_still_a_placeholder(comment):
    assert "placeholder-comment" in rules_in(scan.scan_text("app/a.py", comment + "\nX = 1\n"))


@pytest.mark.parametrize("files", [
    {**BASE_NET, "app/a.py": "from app.net import fetch\nprint(fetch('x'))\neval(input())\n"},
    {**BASE_NET, "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n", "app/fast.pyx": "from app.net import fetch\nprint(fetch('x', retries=2))\n"},
    {"app/net.py": "class M(type):\n    pass\n\n\nclass Client(metaclass=M):\n    def __init__(self, url, timeout=3):\n        self.url = url\n        self.timeout = timeout\n", "app/a.py": "from app.net import Client\nprint(Client('x'))\n"},
], ids=["eval", "cython", "metaclass"])
def test_unused_option_stays_silent_for_these_too(tmp_path, files):
    assert not unused_option_fires(tmp_path, files)


def test_a_computed_getattr_that_is_called_hides_a_call(tmp_path):
    assert not unused_option_fires(tmp_path, {**BASE_NET, "app/a.py": "import app.net as m\nfrom app.net import fetch\nprint(fetch('x'))\nhandler = getattr(m, input())\nprint(handler('x', retries=2))\n"})


def test_reading_an_attribute_by_computed_name_hides_nothing(tmp_path):
    assert unused_option_fires(tmp_path, {**BASE_NET, "app/a.py": "from app.net import fetch\nprint(fetch('x'))\n\n\ndef read(node, field):\n    return getattr(node, field, None)\n\n\nprint(read(object(), 'x'))\n"})
