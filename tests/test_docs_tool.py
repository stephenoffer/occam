"""`occam docs`, run for real: documents against a real repository, and the human-voice linter found the way a user's install is."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_occam_hook import Agent

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "hooks"))
import rule_card  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OCCAM = ROOT / "plugin" / "skills" / "occam" / "scripts" / "occam.py"
GIT = shutil.which("git")
LINTER_PATH = Path("human-voice") / "scripts" / "detect_ai_prose.py"
PROJECT = {
    "pyproject.toml": '[project]\nname = "ledgerkit"\ndependencies = ["requests"]\n[project.scripts]\nledgerkit = "ledgerkit.cli:main"\n',
    "ledgerkit/__init__.py": "from .core import reconcile\n",
    "ledgerkit/core.py": "def reconcile(entries, max_drift=0.01):\n    return entries\n",
    "ledgerkit/cli.py": 'import argparse\ndef main():\n    parser = argparse.ArgumentParser()\n    parser.add_argument("--dry-run", action="store_true")\n    return parser.parse_args()\n',
    "scripts/backfill.py": 'import sys\nif "--since" in sys.argv:\n    print("LEDGER_HOME")\n',
    "docs/usage.md": "# Usage\n",
}


def fake_linter(path: Path, payload: dict | None = None, exit_code: int = 0, marker: Path | None = None) -> Path:
    """A stand-in for detect_ai_prose.py with the real command line. Tests can't depend on what's installed, and the real versions were run by hand."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = payload or {"score": 3.5, "verdict": "clean", "hits": [{"category": "filler"}, {"category": "filler"}, {"category": "jargon"}]}
    touch = f"open({str(marker)!r}, 'w').close()\n" if marker else ""
    path.write_text(f"import json, sys\n{touch}assert sys.argv[1] == '--json' and sys.argv[-1] == '-'\nsys.stdin.read()\n"
                    f"print(json.dumps({body!r}))\nraise SystemExit({exit_code})\n")
    return path


class Project:
    def __init__(self, tmp_path: Path, git: bool = True) -> None:
        self.path = tmp_path / "project"
        self.home = tmp_path / "home"
        self.path.mkdir()
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "OCCAM_STATE_DIR": str(tmp_path / "state"), "PYTHONDONTWRITEBYTECODE": "1", "GIT_AUTHOR_NAME": "t",
                    "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        for name, content in PROJECT.items():
            self.write(name, content)
        if git:
            self.git("init", "-q")
            self.git("add", "-A")
            self.git("commit", "-qm", "init")

    def write(self, name: str, content: str) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def git(self, *args: str) -> None:
        subprocess.run([GIT, *args], cwd=self.path, env=self.env, capture_output=True, check=True)

    def occam(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(OCCAM), *args], cwd=self.path, env=self.env, capture_output=True, text=True, timeout=60)

    def docs(self, text: str, *args: str) -> subprocess.CompletedProcess:
        self.write("README.md", text)
        return self.occam("docs", "README.md", *args)


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path)


def test_a_document_that_matches_the_code_is_clean(project):
    done = project.docs("""# ledgerkit

Call `reconcile()` with `max_drift`, from `ledgerkit/core.py` or `core.py`, and pass `--dry-run`. See [usage](docs/usage.md).

```bash
ledgerkit --dry-run
python3 -m ledgerkit.cli --dry-run
python3 scripts/backfill.py --since 2020
```

```python
from ledgerkit import reconcile
print(reconcile([1]))
```

```json
{"max_drift": 0.01}
```
""")
    assert done.returncode == 0, done.stdout
    assert "facts: 0 leads" in done.stdout


@pytest.mark.parametrize("text, rule, needle", [
    ("Call `reconcile_all()`.", "unknown-name", "reconcile_all"),
    ("Use `Ledger.close`.", "unknown-name", "Ledger.close"),
    ("Set `max_retries`.", "unknown-name", "max_retries"),
    ("Set `maxRetries`.", "unknown-name", "maxRetries"),
    ("Pass `--fast`.", "unknown-name", "--fast"),
    ("See `ledgerkit/missing.py`.", "missing-path", "ledgerkit/missing.py"),
    ("See `missing.py:12`.", "missing-path", "missing.py:12"),
    ("See `scripts/nope/`.", "missing-path", "scripts/nope/"),
    ("See `missing.py:36-38`.", "missing-path", "missing.py:36-38"),
    ("See [guide](docs/guide.md).", "dead-link", "docs/guide.md"),
    ("![logo](assets/logo.png)", "dead-link", "assets/logo.png"),
    ('<img src="assets/logo.png">', "dead-link", "assets/logo.png"),
    ("[guide]: docs/guide.md", "dead-link", "docs/guide.md"),
    ("```bash\nledgerkit --fast\n```", "unknown-name", "--fast"),
    ("```bash\nFOO=1 ledgerkit \\\n  --dry-run \\\n  --fast\n```", "unknown-name", "--fast"),
    ("```console\n$ ledgerkit --fast\nusage: --printed-by-the-tool\n```", "unknown-name", "--fast"),
    ("```bash\npython3 scripts/backfill.py --until 2020\n```", "unknown-name", "--until"),
    ("```bash\npython3 -m ledgerkit.server\n```", "missing-path", "ledgerkit.server"),
    ("```bash\npython3 -m ledgerkit.cli --fast\n```", "unknown-name", "--fast"),
    ("```bash\npython3 scripts/restore.py\n```", "missing-path", "scripts/restore.py"),
    ("```bash\n./scripts/restore.sh\n```", "missing-path", "./scripts/restore.sh"),
    ("```bash\ncd x && ledgerkit --fast\n```", "unknown-name", "--fast"),
    ("```python\nfrom ledgerkit import balance\n```", "unknown-name", "balance"),
    ("```python\nimport ledgerpro\n```", "unknown-name", "ledgerpro"),
    ("```python\n>>> from ledgerkit import balance\n```", "unknown-name", "balance"),
    ("```python\ndef broken(:\n```", "bad-example", "doesn't parse"),
    ("```json\n{\"a\": 1,}\n```", "bad-example", "doesn't parse"),
])
def test_each_kind_of_invention_is_reported_with_its_rule(project, text, rule, needle):
    done = project.docs(f"# Title\n\n{text}\n")
    assert done.returncode == 1, done.stdout
    line = next((line for line in done.stdout.splitlines() if f" {rule}: " in line), "")
    assert needle in line, done.stdout


@pytest.mark.parametrize("text", [
    "Say `and/or`, `application/json`, `n/a`, `GET /items`, `true`, `requests`, `pip install x`, `<placeholder>`, `*.py`, `~/.config/x.toml`, `/etc/hosts`, `$HOME/x.py`.",
    "Standard library: `json.loads`, `os.path.join`. Web: `example.com`. A dunder: `__init__`. Builtin: `print()`.",
    "[site](https://example.com/x.md), [mail](mailto:a@example.com), [here](#usage), [query](docs/usage.md?plain=1), [anchor](docs/usage.md#top), [root](/docs/usage.md).",
    "[`docs/elsewhere.json`](https://example.com/docs/elsewhere.json) names a path on another site.",
    "```bash\ngit commit --amend --no-edit\nnpm install --save-dev x\npip install --upgrade pip\n```",
    "```bash\npython3 -m pytest --maxfail=1\npython3 -c 'print(1)' --anything\n~/bin/tool --flag\n.venv/bin/python --version\n```",
    "```bash\nmytool 'unbalanced --quote\n```",
    "```python\nimport requests\nfrom json import loads\nfrom ledgerkit import *\n```",
    "```yaml\nnot: [checked\n```\n\n```\nno language --flag `missing()`\n```",
    "<!-- `reconcile_all()` and [gone](gone.md) are in a comment -->",
    # The next two came from audit reports agents wrote, where nearly every citation was a line range.
    "Cited as `ledgerkit/core.py:1`, `ledgerkit/core.py:1:5`, `ledgerkit/core.py:1-2`, `ledgerkit/core.py#L1-L2` and `core.py:1-2`.",
    "A value that compares false with itself is `NaN`.",
])
def test_what_it_cannot_judge_stays_quiet(project, text):
    done = project.docs(f"# Title\n\n{text}\n")
    assert done.returncode == 0, done.stdout
    assert "facts: 0 leads" in done.stdout


def test_a_link_resolves_from_the_document_and_not_the_root(project):
    project.write("docs/guide.md", "Root-relative by mistake: [usage](docs/usage.md). Right: [usage](usage.md). Absolute: [usage](/docs/usage.md).\n")
    done = project.occam("docs", "docs/guide.md")
    assert done.returncode == 1
    assert "docs/guide.md:1 dead-link: link to `docs/usage.md`" in done.stdout
    assert "`usage.md`" not in done.stdout and "/docs/usage.md`" not in done.stdout


def test_line_numbers_point_at_the_line(project):
    done = project.docs("line one\n\n```python\nprint(1)\n```\n\n<!-- a\ncomment -->\n\nCall `nope_here()`.\n\n```bash\nledgerkit --dry-run\nledgerkit --fast\n```\n\n```python\nimport os\nimport ledgerpro\n```\n")
    assert "README.md:10 unknown-name: `nope_here()`" in done.stdout
    assert "README.md:14 unknown-name: flag `--fast`" in done.stdout
    assert "README.md:19 unknown-name: example imports `ledgerpro`" in done.stdout


def test_nothing_a_document_shows_is_run(project):
    marker = project.path / "ran"
    done = project.docs(f"```bash\ntouch {marker}\n```\n\n```python\nopen({str(marker)!r}, 'w')\n```\n")
    assert not marker.exists()
    assert done.returncode == 0, done.stdout


def test_output_is_bounded_and_a_lead_does_not_repeat_a_huge_target(project):
    many = " ".join(f"`name_{index}`" for index in range(40))
    done = project.docs(f"{many}\n\n[x]({'a/' * 5000}b.md)\n")
    assert "... and" in done.stdout and len(done.stdout) < 4000


@pytest.mark.parametrize("text", [
    "Pass `--fast=" + "a" * 5000 + "`.",
    "```bash\nledgerkit --fast=" + "a" * 5000 + "\n```",
    "```bash\npython3 " + "a" * 5000 + ".py\n```",
    "```bash\npython3 -m ledgerkit." + "a" * 5000 + "\n```",
    "```python\nimport " + "a" * 5000 + "\n```",
    "```python\nfrom ledgerkit import " + "a" * 5000 + "\n```",
])
def test_no_lead_repeats_a_long_name_from_the_document(project, text):
    done = project.docs(f"{text}\n")
    assert "a" * 400 not in done.stdout


def test_a_partial_index_says_so_rather_than_calling_real_names_unknown(project, monkeypatch):
    monkeypatch.syspath_prepend(str(OCCAM.parent))
    from occam_tools import docs
    project.write("README.md", "Call `reconcile()`.\n")
    monkeypatch.setattr(docs, "_MAX_FILES", 1)
    text, _ = docs.check(project.path, paths=[str(project.path / "README.md")])
    assert "Only the first 1 files were read for names" in text
    assert "Only the first" not in project.docs("Call `reconcile()`.\n").stdout


def test_every_span_on_a_line_is_read(project):
    done = project.docs("Call `nope_one()`, `nope_two()` and `nope_three()`. An `unclosed run, then ``nope_four()`` and ``nope_five()``.\n")
    for name in ("nope_one", "nope_two", "nope_three", "nope_four", "nope_five"):
        assert f"`{name}()` appears nowhere" in done.stdout, done.stdout


def test_a_span_is_closed_by_a_run_of_its_own_length(project):
    done = project.docs("Quoted: ``nope_`six()`` and then `nope_seven()`.\n")
    assert "nope_seven" in done.stdout and "nope_`six" not in done.stdout.replace("`nope_`six()`", "", 1).split("What this")[0].split("facts:")[0]


@pytest.mark.parametrize("package", ['{"name": "tool", "bin": {"mytool": "x.js"}}', '{"name": "mytool", "bin": "x.js"}', '{"name": "@org/mytool", "bin": "x.js"}'])
def test_a_command_from_package_json_is_this_projects_own(project, package):
    project.write("package.json", package)
    done = project.docs("```bash\nmytool --fast\n```\n")
    assert done.returncode == 1 and "flag `--fast` of `mytool`" in done.stdout


@pytest.mark.parametrize("package", ["not json", "[1]", '{"bin": 3}', '{"bin": "x.js"}', '{"name": 3, "bin": "x.js"}'])
def test_a_package_json_naming_no_command_changes_nothing(project, package):
    project.write("package.json", package)
    done = project.docs("```bash\nmytool --fast\n```\n")
    assert done.returncode == 0, done.stdout


@pytest.mark.parametrize("error", [ValueError, RecursionError, MemoryError])
def test_python_that_breaks_the_parser_is_a_lead_and_not_a_crash(project, monkeypatch, error):
    monkeypatch.syspath_prepend(str(OCCAM.parent))
    from occam_tools import docs

    def breaks(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(docs.ast, "parse", breaks)
    index = docs.Index(set(), set(), set(), set(), set(), False)
    leads = docs.document_leads(project.path, "README.md", "```python\nprint(1)\n```\n", index)
    assert [(lead.line, lead.rule) for lead in leads] == [(2, "bad-example")]


@pytest.mark.parametrize("source", ["-" * 200_000 + "1", "print(1)\n" * 1000 + "\0"])
def test_python_built_to_break_the_parser_does_not_crash_the_command(project, source):
    # Whether these parse depends on the interpreter: 3.9 accepts the first one.
    done = project.docs(f"```python\n{source}\n```\n")
    assert done.returncode in (0, 1), done.stderr[-300:]
    assert "Traceback" not in done.stderr


def test_a_hung_linter_is_reported_rather_than_waited_for(project, monkeypatch):
    monkeypatch.syspath_prepend(str(OCCAM.parent))
    from occam_tools import docs
    target = project.home / ".claude/skills" / LINTER_PATH
    target.parent.mkdir(parents=True)
    target.write_text("import time\ntime.sleep(30)\n")
    project.write("README.md", "Plain text.\n")
    monkeypatch.setenv("HOME", str(project.home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(docs, "_LINT_SECONDS", 1)
    text, code = docs.check(project.path, paths=[str(project.path / "README.md")])
    assert code == 1 and "voice: FAILED to run, timed out after 1s" in text


def test_a_hung_linter_takes_what_it_started_with_it(project, monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(OCCAM.parent))
    from occam_tools import docs
    marker = tmp_path / "grandchild-ran"
    target = project.home / ".claude/skills" / LINTER_PATH
    target.parent.mkdir(parents=True)
    target.write_text(f"import subprocess, time\nsubprocess.Popen(['sh', '-c', 'sleep 1.5; touch {marker}'])\ntime.sleep(30)\n")
    project.write("README.md", "Plain text.\n")
    monkeypatch.setenv("HOME", str(project.home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(docs, "_LINT_SECONDS", 1)
    text, _ = docs.check(project.path, paths=[str(project.path / "README.md")])
    assert "timed out after 1s" in text
    time.sleep(2)
    assert not marker.exists()


@pytest.mark.parametrize("name, text", [
    ("open brackets", "[" * 400_000),
    ("unclosed backticks of every length", "".join("`" * length + "a" for length in range(1, 880))),
    ("blank lines", "\n" * 400_000),
    ("blank lines in a block", "```python\n" + "\n" * 400_000 + "```"),
    ("empty blocks", "```\n" * 100_000),
    ("assignments", "```bash\n" + "a=1 " * 100_000 + "\n```"),
    ("a long name", "`" + "a_" * 200_000 + "!`"),
])
def test_a_document_built_to_be_slow_is_not(project, name, text):
    project.write("README.md", text)
    project.write("before.md", "plain\n")
    started = time.monotonic()
    done = project.occam("docs", "README.md", "--before", "before.md")
    assert time.monotonic() - started < 20, name
    assert done.returncode in (0, 1), done.stderr


# ---------------------------------------------------------------- which documents

def test_with_no_paths_it_checks_only_changed_documents(project):
    project.write("docs/usage.md", "Call `nope_here()`.\n")
    project.write("docs/untracked.md", "Call `other_nope()`.\n")
    project.write("ledgerkit/core.py", PROJECT["ledgerkit/core.py"] + "# touched\n")
    project.write("docs/committed.md", "Call `committed_nope()`.\n")
    project.git("add", "docs/committed.md")
    project.git("commit", "-qm", "another")
    done = project.occam("docs")
    assert done.returncode == 1
    assert "2 documents" in done.stdout and "nope_here" in done.stdout and "other_nope" in done.stdout
    assert "committed_nope" not in done.stdout


def test_a_deleted_document_is_not_a_failure(project):
    (project.path / "docs" / "usage.md").unlink()
    done = project.occam("docs")
    assert done.returncode == 0 and "No changed documents" in done.stdout


def test_a_clean_tree_has_nothing_to_check(project):
    done = project.occam("docs")
    assert done.returncode == 0 and "No changed documents" in done.stdout


def test_without_git_it_asks_for_names_rather_than_reporting_clean(tmp_path):
    bare = Project(tmp_path, git=False)
    done = bare.occam("docs")
    assert done.returncode == 2 and "Name the documents" in done.stdout
    assert bare.occam("docs", "docs/usage.md").returncode == 0


@pytest.mark.parametrize("args, says", [
    (("nowhere.md",), "No such path"),
    (("ledgerkit/core.py",), "No documents in"),
    (("docs/usage.md", "--before", "nowhere.md"), "No such path"),
    (("docs", "--before", "docs/usage.md"), "exactly one document"),
])
def test_nothing_checked_is_never_a_clean_exit(project, args, says):
    done = project.occam("docs", *args)
    assert done.returncode == 2 and says in done.stdout and "Nothing was checked" in done.stdout


def test_a_path_outside_the_project_is_refused(project, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("hello\n")
    done = project.occam("docs", "--root", str(project.path), str(outside))
    assert done.returncode == 2 and "outside this project" in done.stdout


def test_other_prose_says_its_facts_were_not_checked(project):
    project.write("guide.rst", "Call ``nope_here()``.\n")
    done = project.occam("docs", "guide.rst")
    assert done.returncode == 2  # nothing's facts were read, so this can't exit as if they were fine
    assert "NOT CHECKED, because only Markdown is parsed" in done.stdout


def test_a_folder_is_walked_and_its_code_ignored(project):
    project.write("docs/conf.py", "project = 1\n")
    done = project.occam("docs", "docs")
    assert done.returncode == 0 and "1 document." in done.stdout and "conf.py" not in done.stdout


# ---------------------------------------------------------------- what a rewrite changed

@pytest.mark.parametrize("before, after, expected", [
    ("Retries 3 times after 30s.", "Retries a few times.", ["lost number: 3", "lost number: 30s"]),
    ("Retries 3 times.", "Retries 5 times.", ["lost number: 3", "added number: 5"]),
    ("Uses 40% of 1,200 rows in v1.2.3 by 2026-09-16.", "Uses some rows.", ["lost number: 40%", "lost number: 1200", "lost number: v1.2.3", "lost number: 2026-09-16"]),
    ("Calls `reconcile`.", "Calls it.", ["lost code: reconcile"]),
    ("Calls it.", "Calls `reconcile`.", ["added code: reconcile"]),
    ("See [a](docs/usage.md).", "See the usage page.", ["lost link: docs/usage.md"]),
    ("See https://example.com/a for more.", "See the site.", ["lost link: https://example.com/a"]),
    ("```bash\nledgerkit --dry-run\n```", "```bash\nledgerkit\n```", ["lost code block: ledgerkit --dry-run", "added code block: ledgerkit"]),
])
def test_before_reports_what_a_rewrite_lost_or_added(project, before, after, expected):
    project.write("before.md", before + "\n")
    done = project.docs(after + "\n", "--before", "before.md")
    assert done.returncode == 1, done.stdout
    for change in expected:
        assert change in done.stdout


@pytest.mark.parametrize("before, after", [
    ("It robustly leverages `reconcile` with 3 retries.", "With 3 retries, it calls `reconcile`."),
    ("Uses 1,200 rows.", "Rows used: 1200."),
    ("1. First step takes 30s.\n2. Second step.", "- First step takes 30s.\n- Second step."),
    ("Said once: `reconcile`, 3. Said again: `reconcile`, 3.", "Said once: `reconcile`, 3."),
    ("See https://example.com/a for more.", "For more, see https://example.com/a."),
    ("```bash\n  ledgerkit --dry-run\n```", "Run:\n\n```bash\n  ledgerkit --dry-run\n```"),
])
def test_before_stays_quiet_when_only_the_prose_moved(project, before, after):
    project.write("before.md", before + "\n")
    done = project.docs(after + "\n", "--before", "before.md")
    assert done.returncode == 0, done.stdout
    assert "no number, code, link or code block changed" in done.stdout


# ---------------------------------------------------------------- the human-voice linter

def test_a_missing_linter_is_reported_and_does_not_fail(project):
    done = project.docs("Plain text.\n")
    assert done.returncode == 0
    assert "voice: not run" in done.stdout and "Don't report the prose as checked" in done.stdout


def test_the_plugin_install_is_found_and_the_score_never_fails_the_command(project):
    fake_linter(project.home / ".claude/plugins/cache/mp/human-voice/0.9.0/skills" / LINTER_PATH, {"score": 99.0, "verdict": "strong-tell", "hits": [{"category": "filler"}]})
    done = project.docs("Plain text.\n")
    assert done.returncode == 0, done.stdout
    assert "voice: 99.0, strong-tell. filler 1" in done.stdout and "Voice came from" in done.stdout and "floor" in done.stdout


def test_the_newest_plugin_version_wins_numerically(project):
    for version, score in (("0.9.0", 1.0), ("0.10.0", 2.0), ("0.1.0", 3.0), ("unknown", 4.0)):
        fake_linter(project.home / f".claude/plugins/cache/mp/human-voice/{version}/skills" / LINTER_PATH, {"score": score, "hits": []})
    assert "voice: 2.0," in project.docs("Plain text.\n").stdout


def test_a_config_dir_moves_where_plugins_are_found(project, tmp_path):
    fake_linter(tmp_path / "elsewhere/plugins/cache/mp/human-voice/0.9.0/skills" / LINTER_PATH, {"score": 7.0, "verdict": "watch", "hits": []})
    project.env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "elsewhere")
    assert "voice: 7.0, watch" in project.docs("Plain text.\n").stdout


@pytest.mark.parametrize("folder", [".claude/skills", ".agents/skills", ".config/opencode/skills"])
def test_a_plain_user_copy_is_found(project, folder):
    fake_linter(project.home / folder / LINTER_PATH, {"score": 1.5, "verdict": "clean", "hits": []})
    done = project.docs("Plain text.\n")
    assert "voice: 1.5, clean. no tells matched" in done.stdout


def test_a_copy_in_the_repository_needs_allow_exec_because_it_is_repository_code(project, tmp_path):
    marker = tmp_path / "linter-ran"
    fake_linter(project.path / ".claude/skills" / LINTER_PATH, {"score": 2.0, "verdict": "clean", "hits": []}, marker=marker)
    refused = project.docs("Plain text.\n")
    assert refused.returncode == 0
    assert not marker.exists()
    assert "inside this repository" in refused.stdout and "--allow-exec" in refused.stdout
    allowed = project.occam("docs", "README.md", "--allow-exec")
    assert marker.exists()
    assert "voice: 2.0, clean" in allowed.stdout


def test_a_symlink_cannot_carry_repository_code_past_allow_exec(project, tmp_path):
    marker = tmp_path / "linter-ran"
    fake_linter(project.path / "tools/evil/scripts/detect_ai_prose.py", {"score": 2.0, "hits": []}, marker=marker)
    (project.home / ".claude/skills").mkdir(parents=True)
    (project.home / ".claude/skills/human-voice").symlink_to(project.path / "tools/evil")
    refused = project.docs("Plain text.\n")
    assert not marker.exists() and "--allow-exec" in refused.stdout


def test_a_project_symlink_pointing_outside_still_needs_allow_exec(project, tmp_path):
    marker = tmp_path / "linter-ran"
    fake_linter(tmp_path / "outside/scripts/detect_ai_prose.py", {"score": 2.0, "hits": []}, marker=marker)
    (project.path / ".claude/skills").mkdir(parents=True)
    (project.path / ".claude/skills/human-voice").symlink_to(tmp_path / "outside")
    refused = project.docs("Plain text.\n")
    assert not marker.exists() and "--allow-exec" in refused.stdout


def test_a_repository_copy_does_not_stop_the_users_own_from_running(project):
    fake_linter(project.path / ".claude/skills" / LINTER_PATH, {"score": 2.0, "hits": []})
    fake_linter(project.home / ".claude/skills" / LINTER_PATH, {"score": 8.0, "verdict": "watch", "hits": []})
    assert "voice: 8.0, watch" in project.docs("Plain text.\n").stdout


def test_a_broken_linter_is_a_failure_and_not_a_pass(project):
    fake_linter(project.home / ".claude/skills" / LINTER_PATH, exit_code=2)
    done = project.docs("Plain text.\n")
    assert done.returncode == 1
    assert "voice: FAILED to run, exit 2" in done.stdout and "Voice came from" not in done.stdout


@pytest.mark.parametrize("script", ["print('not json')\n", "print('[1]')\n", "print('{\"no\": \"score\"}')\n"])
def test_unreadable_linter_output_is_a_failure(project, script):
    target = project.home / ".claude/skills" / LINTER_PATH
    target.parent.mkdir(parents=True)
    target.write_text(script)
    done = project.docs("Plain text.\n")
    assert done.returncode == 1 and "voice: FAILED to run" in done.stdout


def test_an_older_linter_with_no_bands_is_labeled(project):
    fake_linter(project.home / ".claude/skills" / LINTER_PATH, {"score": 545.5, "hits": []})
    assert "no band" in project.docs("Plain text.\n").stdout


def test_register_reaches_the_linter(project):
    target = project.home / ".claude/skills" / LINTER_PATH
    target.parent.mkdir(parents=True)
    target.write_text("import json, sys\nprint(json.dumps({'score': 1, 'verdict': sys.argv[sys.argv.index('--register') + 1], 'hits': []}))\n")
    assert "voice: 1, tutorial." in project.docs("Plain text.\n", "--register", "tutorial").stdout


def test_before_shows_both_scores_from_one_linter(project):
    target = project.home / ".claude/skills" / LINTER_PATH
    target.parent.mkdir(parents=True)
    target.write_text("import json, sys\nprint(json.dumps({'score': len(sys.stdin.read()), 'verdict': 'x', 'hits': []}))\n")
    project.write("before.md", "A much longer first draft.\n")
    done = project.docs("Short.\n", "--before", "before.md")
    assert "voice: 27 before, 7 now" in done.stdout


# ---------------------------------------------------------------- gate

def test_gate_warns_about_a_changed_document_and_does_not_block(project):
    project.write("docs/usage.md", "Call `nope_here()`.\n")
    done = project.occam("gate")
    assert done.returncode == 0, done.stdout
    assert "warn  Documents match the code" in done.stdout and "docs/usage.md:1  unknown-name" in done.stdout


def test_gate_says_nothing_about_documents_when_none_changed(project):
    project.write("ledgerkit/core.py", PROJECT["ledgerkit/core.py"] + "# touched\n")
    assert "Documents match the code" not in project.occam("gate").stdout


def test_gate_strict_blocks_on_it(project):
    project.write("docs/usage.md", "Call `nope_here()`.\n")
    assert project.occam("gate", "--strict").returncode == 1


# ---------------------------------------------------------------- the hook's pointer

@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path)


def pointer_in(result) -> bool:
    return bool(result) and "occam-docs" in result["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("name", ["README.md", "docs/guide.md", "notes.mdx", "guide.rst"])
def test_editing_a_document_points_at_the_skill_once_and_holds_nothing(agent, name):
    before = (agent.try_edit(name) or {}).get("hookSpecificOutput") or {}
    assert not before.get("permissionDecision") and before.get("additionalContext", "") in ("", rule_card.CARD), "holds nothing; the first tool call carries only the rule card"
    first = agent.edit(name)
    assert pointer_in(first)
    assert str(OCCAM) in first["hookSpecificOutput"]["additionalContext"]
    assert "human-voice" in first["hookSpecificOutput"]["additionalContext"]
    assert not pointer_in(agent.edit("OTHER.md"))


def test_the_pointer_is_silent_once_the_skill_has_loaded(agent):
    agent.load("occam:occam-docs")
    assert not pointer_in(agent.edit("README.md"))


@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md", "skills/x/SKILL.md", "data.csv", "notes.txt", "app.css"])
def test_files_that_are_not_documents_for_readers_get_no_pointer(agent, name):
    assert not pointer_in(agent.edit(name))


@pytest.mark.parametrize("prompt", [
    "write a README for this module", "add docs for the new endpoint", "generate an API reference", "update the documentation",
    "document this function", "draft the release notes", "add docstrings to the parser", "Please make a usage guide",
])
def test_asking_for_documentation_points_at_the_skill_before_anything_is_written(agent, prompt):
    assert pointer_in(agent.prompt(prompt))
    assert not pointer_in(agent.edit("README.md"))


@pytest.mark.parametrize("prompt", [
    "fix the docker build", "write a test for the parser", "the docs say this should work, why does it fail?", "add retries to the client",
    "review the README, don't change anything",
])
def test_other_requests_get_no_pointer(agent, prompt):
    assert not pointer_in(agent.prompt(prompt))


def test_typing_the_skill_needs_no_pointer(agent):
    assert not pointer_in(agent.prompt("/occam:occam-docs write a README"))
