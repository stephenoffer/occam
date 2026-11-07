"""The shared design doc in `occam gate`: what it notices about a change, and that it only warns."""

import subprocess
import sys

import pytest

from design_support import DOC, Repo, _history, _stock, design, design_tool, stock_only

pytest_plugins = ("design_support",)  # its `repo` and `agent` fixtures


def test_gate_notes_cited_code_changing_while_the_doc_does_not(repo):
    repo.write("app/billing.py", "def charge(cents):\n    return cents + 1\n\n\nprint(charge(1))\n")
    done = repo.occam("gate")
    assert "design-not-updated" in done.stdout and "app/billing.py" in done.stdout


def test_gate_says_nothing_about_code_the_doc_does_not_cite(repo):
    repo.write("other.py", "print(9)\n")
    assert "design-not-updated" not in repo.occam("gate").stdout


def test_gate_is_quiet_when_the_doc_changed_too(repo):
    repo.write("app/billing.py", "def charge(cents):\n    return cents + 1\n\n\nprint(charge(1))\n")
    repo.occam("design", "decide", "bump", "Add one", "--why", "fees", "--applies", "app/billing.py")
    done = repo.occam("gate").stdout
    assert "design-not-updated" not in done and "decision-rewritten" not in done


@pytest.mark.parametrize("edit, word", [
    (lambda text: text.replace("Money is integer cents", "Money is floats"), "edited"),
    (lambda text: text.replace("- 2026-01-01 use-cents [accepted] Money is integer cents. Why: floats lost pennies. Applies: `app/billing.py`.\n", ""), "removed"),
])
def test_gate_notes_a_decision_rewritten_rather_than_superseded(repo, edit, word):
    repo.write("DESIGN.md", edit(DOC))
    done = repo.occam("gate").stdout
    assert "decision-rewritten" in done and word in done


def test_accepting_a_proposal_is_not_a_rewrite(repo):
    repo.occam("design", "decide", "queue-yes", "Add the queue", "--why", "spikes", "--supersedes", "maybe-queue")
    assert "decision-rewritten" not in repo.occam("gate").stdout


def test_gate_notes_do_not_block(repo):
    repo.write("app/billing.py", "def charge(cents):\n    return cents + 1\n\n\nprint(charge(1))\n")
    assert repo.occam("gate").returncode == 0


def test_gate_does_not_treat_planned_names_as_missing(repo):
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.", "Shops lose many orders."))
    assert "queue.py" not in repo.occam("gate").stdout


def test_gate_notes_a_usual_partner_left_out(repo):
    _history(repo, 6)
    repo.write("app/rates.py", "RATE = 99\n")
    done = repo.occam("gate").stdout
    assert "usual-partner" in done and "app/rates_table.py" in done and "of its last" in done


def test_no_note_when_the_partner_is_in_the_change(repo):
    _history(repo, 6)
    repo.write("app/rates.py", "RATE = 99\n")
    repo.write("app/rates_table.py", "TABLE = 99\n")
    assert "usual-partner" not in repo.occam("gate").stdout


def test_too_little_history_says_nothing(repo):
    _history(repo, 3)
    repo.write("app/rates.py", "RATE = 99\n")
    assert "usual-partner" not in repo.occam("gate").stdout


def test_a_sometimes_partner_says_nothing(repo):
    _history(repo, 3)
    for index in range(4):
        repo.write("app/rates.py", f"RATE = {index + 10}\n")
        repo.commit()
    repo.write("app/rates.py", "RATE = 99\n")
    assert "usual-partner" not in repo.occam("gate").stdout


def test_a_lockfile_is_not_a_partner(repo):
    for index in range(6):
        repo.write("app/rates.py", f"RATE = {index}\n")
        repo.write("uv.lock", f"v{index}\n")
        repo.commit()
    repo.write("app/rates.py", "RATE = 99\n")
    assert "usual-partner" not in repo.occam("gate").stdout


def test_crlf_does_not_look_like_every_decision_was_rewritten(repo):
    crlf = DOC.replace("\n", "\r\n").encode()
    (repo.path / "DESIGN.md").write_bytes(crlf)
    repo.commit()
    (repo.path / "DESIGN.md").write_bytes(crlf.replace(b"Shops lose orders.", b"Shops lose many orders."))
    assert "decision-rewritten" not in repo.occam("gate").stdout


def test_a_doc_changed_to_crlf_is_not_a_rewrite(repo):
    (repo.path / "DESIGN.md").write_bytes(DOC.replace("\n", "\r\n").encode())
    assert "decision-rewritten" not in repo.occam("gate").stdout


@pytest.mark.parametrize("content, as_bytes", [(b"\x00\x01binary", True)])
def test_for_does_not_say_nothing_applies_when_it_could_not_read(repo, content, as_bytes):
    (repo.path / "DESIGN.md").write_bytes(content)
    done = repo.occam("design", "for", "app/billing.py")
    assert done.returncode == 2 and "NOT CHECKED" in done.stdout and "nothing specific" not in done.stdout
    assert "couldn't be read" in repo.occam("design", "decide", "fresh", "Text", "--why", "y").stdout
    assert "design-unreadable" in repo.occam("gate").stdout


@pytest.mark.parametrize("change", ["delete", "rename", "delete-folder"])
def test_gate_notes_cited_code_going_away(repo, change):
    if change == "delete":
        (repo.path / "app/billing.py").unlink()
    elif change == "rename":
        repo.git("mv", "app/billing.py", "app/charges.py")
    else:
        (repo.path / "app/web/routes.py").unlink()
    assert "design-not-updated" in repo.occam("gate").stdout


def test_gate_notes_the_document_being_removed(repo):
    (repo.path / "DESIGN.md").unlink()
    done = repo.occam("gate").stdout
    assert "design-removed" in done and "2 decisions in force" in done


def test_gate_compares_a_moved_document_with_what_it_was(repo):
    (repo.path / "docs").mkdir(exist_ok=True)
    repo.git("mv", "DESIGN.md", "docs/DESIGN.md")
    assert "decision-rewritten" not in repo.occam("gate").stdout
    repo.write("docs/DESIGN.md", DOC.replace("Money is integer cents", "Money is floats"))
    assert "decision-rewritten" in repo.occam("gate").stdout


def test_a_new_document_hiding_the_old_one_is_noted(repo):
    (repo.path / "docs").mkdir(exist_ok=True)
    repo.git("mv", "DESIGN.md", "docs/DESIGN.md")
    repo.commit()
    repo.write("DESIGN.md", DOC.replace("- 2026-01-01 use-cents [accepted] Money is integer cents. Why: floats lost pennies. Applies: `app/billing.py`.\n", ""))
    out = repo.occam("gate").stdout
    assert "design-shadowed" in out and "decision-rewritten" not in out


def test_gate_does_not_claim_a_named_path_left_the_doc_unchanged(repo):
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.", "Shops lose many orders."))
    repo.write("app/billing.py", "print(2)\n")
    out = repo.occam("gate", "app/billing.py").stdout
    assert "and it didn't change" not in out and "isn't in this change" not in out


def test_gate_from_outside_or_below_still_checks(repo, tmp_path):
    """The co-change check once made `gate --root` from elsewhere give up, and went quiet from a subfolder."""
    _history(repo, 6)
    repo.write("app/rates.py", "RATE = 99\n")
    outside = subprocess.run([sys.executable, str(design_tool()), "gate", "--root", str(repo.path)], cwd=tmp_path, env=repo.env, capture_output=True, text=True)
    assert "outside this project" not in outside.stdout and "usual-partner" in outside.stdout
    below = subprocess.run([sys.executable, str(design_tool()), "gate"], cwd=repo.path / "app", env=repo.env, capture_output=True, text=True)
    assert "usual-partner" in below.stdout


def test_a_shallow_clone_has_too_little_history_to_say(repo, tmp_path):
    _history(repo, 8)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--depth", "6", f"file://{repo.path}", str(clone)], check=True, env=repo.env, capture_output=True)
    (clone / "app/rates.py").write_text("RATE = 99\n")
    done = subprocess.run([sys.executable, str(design_tool()), "gate"], cwd=clone, env=repo.env, capture_output=True, text=True)
    assert "usual-partner" not in done.stdout


def test_decisions_a_change_stopped_reading_are_not_called_removed(repo):
    for changed in (DOC.replace("## Decisions", "```\n\n## Decisions"), DOC.replace("## Decisions", "## Decision log")):
        repo.write("DESIGN.md", changed)
        out = repo.occam("gate").stdout
        line = changed.split("\n").index(next(line for line in changed.split("\n") if " use-cents " in line)) + 1
        assert f"DESIGN.md:{line}  decision-unread" in out and "use-cents was removed" not in out


def test_a_decision_really_gone_is_still_called_removed(repo):
    repo.write("DESIGN.md", DOC.replace("- 2026-01-01 use-cents [accepted] Money is integer cents. Why: floats lost pennies. Applies: `app/billing.py`.\n", ""))
    assert "use-cents was removed" in repo.occam("gate").stdout


def test_naming_a_clean_file_to_gate_is_not_changing_it(repo):
    out = repo.occam("gate", "app/billing.py").stdout
    assert "design-not-updated" not in out


def test_naming_a_changed_file_to_gate_still_gets_the_note(repo):
    repo.write("app/billing.py", "print(2)\n")
    repo.write("other.py", "print(4)\n")
    out = repo.occam("gate", "app/billing.py").stdout
    assert "This change touches app/billing.py, which DESIGN.md cites" in out
    assert "other.py" not in out.split("design-not-updated")[1].split("\n")[0]


def test_a_link_or_an_anchor_is_a_citation(repo):
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.\n- Routes live in `app/web/`.", "Entry is [the handler](app/billing.py), and the helper is `app/retry.py#L10`.\n\nSee [the guide](https://example.com/a.py) and [above](#problem)."))
    for path in ("app/billing.py", "app/retry.py"):
        assert "now: Entry is" in repo.occam("design", "for", path).stdout
    assert design._cited("See [the guide](https://example.com/a.py) and [above](#problem).") == []
    repo.commit()
    repo.write("app/retry.py", "print(3)\n")
    assert "This change touches app/retry.py" in repo.occam("gate").stdout


def test_removing_the_document_being_read_is_noticed_beside_another(repo):
    repo.write("docs/DESIGN.md", DOC.replace("- 2026-01-01 use-cents [accepted] Money is integer cents. Why: floats lost pennies. Applies: `app/billing.py`.\n", ""))
    repo.commit()
    repo.git("rm", "-q", "DESIGN.md")
    assert "use-cents was removed" in repo.occam("gate").stdout


@stock_only
@pytest.mark.parametrize("with_root_doc", [False, True])
def test_an_unreadable_docs_folder_does_not_crash_on_the_stock_python(repo, with_root_doc):
    if not with_root_doc:
        repo.git("rm", "-q", "--cached", "DESIGN.md")
        (repo.path / "DESIGN.md").unlink()
    (repo.path / "docs").mkdir()
    (repo.path / "docs").chmod(0)
    try:
        for args in (("gate",), ("design", "check")):
            done = _stock(repo, *args)
            assert "Traceback" not in done.stderr, done.stderr
    finally:
        (repo.path / "docs").chmod(0o755)


@pytest.mark.parametrize("change", [("rm", "-q", "app/retry.py"), ("mv", "app/retry.py", "app/retry2.py")])
def test_gating_a_folder_sees_a_cited_file_leave(repo, change):
    repo.git(*change)
    out = repo.occam("gate", "app").stdout
    assert "design-not-updated" in out and "app/retry.py" in out.split("design-not-updated")[1].split("\n")[0]


def test_gating_a_named_file_outside_git_still_works(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "DESIGN.md").write_text(DOC)
    (folder / "a.py").write_text("print(1)\n")
    done = Repo(folder, tmp_path / "state").occam("gate", "a.py")
    assert "Nothing was checked" not in done.stdout and "Traceback" not in done.stderr


def test_gate_prints_what_the_terminal_cannot_show(repo):
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.", "- Billing lives in `app/\u65e5\u672c.py`."))
    done = subprocess.run([sys.executable, str(design_tool()), "gate"], cwd=repo.path, env={**repo.env, "PYTHONIOENCODING": "ascii"}, capture_output=True, text=True)
    assert "Traceback" not in done.stderr and "occam gate:" in done.stdout


def test_gating_the_new_name_sees_a_cited_file_renamed(repo):
    repo.git("mv", "app/retry.py", "app/retry2.py")
    out = repo.occam("gate", "app/retry2.py").stdout
    assert "design-not-updated" in out and "app/retry.py" in out.split("design-not-updated")[1].split("\n")[0]


def test_a_note_about_an_unread_decision_points_only_at_what_is_true(repo):
    line = next(line for line in DOC.split("\n") if " use-cents " in line)
    repo.write("DESIGN.md", DOC.replace(line, f"<!--\n{line}\n-->"))
    out = repo.occam("gate").stdout
    assert "decision-unread" in out and "says why" not in out and "inside a comment" in out
