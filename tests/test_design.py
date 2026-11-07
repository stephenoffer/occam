"""The shared design doc: what `occam design` says and what it refuses."""

import re
import shlex
import subprocess
import sys
import time

import pytest

from design_support import DOC, ROOT, Repo, STOCK_PYTHON, _decision_ids, _hand_written, _stock, _verified, design, design_tool, stock_only

pytest_plugins = ("design_support",)  # its `repo` and `agent` fixtures


def test_only_accepted_unsuperseded_decisions_are_in_force():
    assert [decision.id for decision in design.in_force(design.parse(DOC))] == ["use-cents", "new-idea"]


def test_a_proposal_cannot_supersede_anything():
    text = DOC + "- 2026-01-05 no-cents [proposed] Use floats. Why: simpler. Supersedes: `use-cents`.\n"
    assert "use-cents" in [decision.id for decision in design.in_force(design.parse(text))]


def test_for_gives_what_applies_and_not_the_document(repo):
    out = repo.occam("design", "for", "app/billing.py").stdout
    assert "use-cents" in out and "returns cents" in out and "Billing lives" in out and "Multi-currency" in out
    assert "Routes live" not in out and "old-idea" not in out and "new-idea" not in out


def test_for_marks_what_is_only_proposed_or_planned(repo):
    billing, queue = repo.occam("design", "for", "app/billing.py").stdout, repo.occam("design", "for", "app/queue.py").stdout
    assert "proposed, not decided: 2026-01-04 maybe-queue" in billing
    assert "planned, not built" in queue and "now:" not in queue


def test_for_covers_files_under_a_cited_folder(repo):
    assert "Routes live" in repo.occam("design", "for", "app/web/routes.py").stdout


def test_a_superseded_decision_is_not_shown_as_in_force(repo):
    out = repo.occam("design", "for", "app/retry.py").stdout
    assert "new-idea" in out and "old-idea" not in out.replace("Supersedes: `old-idea`", "")


def test_for_says_when_nothing_applies(repo):
    assert "nothing specific" in repo.occam("design", "for", "other.py").stdout


def test_a_similar_path_is_not_covered(repo):
    repo.write("app/billing.py.bak", "x\n")
    assert "use-cents" not in repo.occam("design", "for", "app/billing.py.bak").stdout
    assert "Routes live" not in repo.occam("design", "for", "app/webhooks.py").stdout


def test_the_code_wins_is_said_every_time(repo):
    assert "the code is right" in repo.occam("design", "for", "other.py").stdout


def test_no_doc_is_fine(tmp_path):
    made = Repo(tmp_path, tmp_path / "state")
    assert made.occam("design", "check").returncode == 0 and "That's fine" in made.occam("design", "check").stdout
    assert "No design doc" in made.occam("design", "for", "a.py").stdout


def test_init_writes_a_doc_that_says_what_is_unfilled(repo):
    (repo.path / "DESIGN.md").unlink()
    done = repo.occam("design", "init")
    assert done.returncode == 0
    text = (repo.path / "DESIGN.md").read_text()
    assert "the code is right" in text and repo.git("rev-parse", "--short", "HEAD").strip() in text
    out = repo.occam("design", "check")
    assert out.returncode == 1 and "placeholder" in out.stdout


def test_init_refuses_to_overwrite(repo):
    assert repo.occam("design", "init").returncode == 2
    assert (repo.path / "DESIGN.md").read_text() == DOC


def test_init_outside_git_claims_no_commit(tmp_path):
    made = Repo(tmp_path, tmp_path / "state")
    made.occam("design", "init")
    assert "Not yet verified" in (tmp_path / "DESIGN.md").read_text()


@pytest.mark.parametrize("edit, rule", [
    (lambda text: text.replace("## Non-goals\n\n- Multi-currency.\n\n", ""), "missing-section"),
    (lambda text: text + "\n## After\n\nx\n", "decisions-not-last"),
    (lambda text: text + "- not a decision\n", "malformed-decision"),
    (lambda text: text + "- 2026-02-01 use-cents [accepted] Again. Why: x.\n", "duplicate-decision"),
    (lambda text: text + "- 2026-02-01 fresh [accepted] New. Why: x. Supersedes: `ghost`.\n", "unknown-supersedes"),
    (lambda text: text.replace("Shops lose orders.", "<Who has what problem, why now, and how much it's worth spending on.>"), "placeholder"),
])
def test_check_blocks_on_a_broken_document(repo, edit, rule):
    repo.write("DESIGN.md", edit(DOC))
    done = repo.occam("design", "check")
    assert done.returncode == 1 and rule in done.stdout


def test_check_finds_a_cited_path_that_does_not_exist(repo):
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Routes live in `app/gone/routes.py`."))
    assert "app/gone/routes.py" in repo.occam("design", "check").stdout


def test_what_is_planned_may_name_what_does_not_exist(repo):
    assert "queue.py" not in repo.occam("design", "check").stdout, "Planned describes what isn't built"


def test_superseded_decisions_are_not_checked_against_the_code(repo):
    repo.write("DESIGN.md", DOC.replace("Applies: `app/retry.py`. Supersedes", "Applies: `app/retry.py`. Supersedes").replace("Retry three times. Why: guess. Applies: `app/retry.py`.", "Retry three times. Why: guess. Applies: `app/gone.py`."))
    assert "app/gone.py" not in repo.occam("design", "check").stdout


def test_check_reports_commits_touching_what_it_cites(repo):
    head = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.write("DESIGN.md", DOC.replace("0000000", head))
    repo.commit()
    head = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.write("DESIGN.md", DOC.replace("0000000", head))
    repo.commit()
    head_two = repo.git("rev-parse", "--short", "HEAD~1").strip()
    repo.write("DESIGN.md", DOC.replace("0000000", head_two))
    repo.write("app/billing.py", "def charge(cents):\n    return cents + 1\n\n\nprint(charge(1))\n")
    repo.commit()
    out = repo.occam("design", "check").stdout
    assert "commit since" in out and "may be stale" in out


def test_check_reports_a_cited_file_renamed_since(repo):
    repo.write("DESIGN.md", DOC.replace("0000000", repo.git("rev-parse", "--short", "HEAD").strip()))
    repo.commit()
    repo.git("mv", "app/billing.py", "app/payments.py")
    repo.commit()
    assert "Renamed or deleted since" in repo.occam("design", "check").stdout


def test_an_unrelated_commit_is_not_called_drift(repo):
    repo.write("DESIGN.md", DOC.replace("0000000", repo.git("rev-parse", "--short", "HEAD").strip()))
    repo.commit()
    repo.write("other.py", "print(4)\n")
    repo.commit()
    assert "may be stale" not in repo.occam("design", "check").stdout


def test_an_unknown_verified_commit_is_said_plainly(repo):
    assert "isn't in this history" in repo.occam("design", "check").stdout


def test_outside_git_drift_is_named_as_not_checked(tmp_path):
    made = Repo(tmp_path, tmp_path / "state")
    made.write("DESIGN.md", DOC)
    assert "NOT CHECKED" in made.occam("design", "check").stdout


def test_a_very_long_document_is_flagged(repo):
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.\n", "Shops lose orders.\n" + "line\n" * 300))
    assert "too-long" in repo.occam("design", "check").stdout


def test_session_note_only_when_there_is_a_doc(tmp_path):
    sys.path.insert(0, str(ROOT / "plugin" / "hooks"))
    import design_notes
    assert design_notes.session_note(str(tmp_path)) == ""
    (tmp_path / "DESIGN.md").write_text(DOC)
    note = design_notes.session_note(str(tmp_path))
    assert "DESIGN.md" in note and "the code is right" in note and "Multi-currency" not in note, "a pointer, not the document"


def test_no_verified_line_is_said_plainly(repo):
    (repo.path / "DESIGN.md").write_text(DOC.replace("Owner: Sam. Verified 2026-01-01 against 0000000.\n", "Owner: Sam.\n"))
    out, _ = design.check(repo.path)
    assert "No `Verified <date> against <commit>` line" in out


def test_a_long_line_is_clipped_to_the_limit():
    limit = design.MAX_NOTE
    assert design.clip("x" * limit) == "x" * limit
    clipped = design.clip("x" * (limit + 1))
    assert len(clipped) == limit and clipped.endswith("...")


def test_a_section_stops_before_the_next_heading():
    parsed = design.parse(DOC)
    assert design._section_lines(parsed, "Non-goals") == ["- Multi-currency."]
    assert parsed.sections["Decisions"][-1][1] == len(DOC.split("\n"))


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
def test_a_fenced_example_is_not_a_decision(fence):
    example = f"{fence}\n- 2026-01-09 fake [accepted] Example. Why: demo. Applies: `app/billing.py`. Supersedes: `use-cents`.\n{fence}\n"
    assert _decision_ids(DOC + example) == ["use-cents", "new-idea"]


def test_a_fenced_heading_is_not_a_section():
    parsed = design.parse(DOC + "~~~\n## Decisions\n- 2026-01-09 fake [accepted] Example. Why: demo.\n~~~\n")
    assert "fake" not in [decision.id for decision in parsed.decisions] and "use-cents" in [decision.id for decision in parsed.decisions]


def test_a_fence_only_closes_on_its_own_kind():
    text = DOC.replace("Shops lose orders.\n", "````\n```\n## Decisions\n```\n~~~\n````\n\n```python\n```text\n## Non-goals\n```\n")
    assert [decision.id for decision in design.parse(text).decisions] == ["use-cents", "old-idea", "new-idea", "maybe-queue"]


def test_inline_triple_backticks_do_not_open_a_fence():
    text = DOC.replace("Shops lose orders.\n", "```x``` starts this line.\n")
    assert _decision_ids(text) == ["use-cents", "new-idea"]


def test_a_section_twice_is_a_problem_and_nothing_vanishes(repo):
    repo.write("DESIGN.md", DOC + "\n## Decisions\n\nNothing more.\n")
    done = repo.occam("design", "check")
    assert done.returncode == 1 and "duplicate-section" in done.stdout
    assert "use-cents" in repo.occam("design", "for", "app/billing.py").stdout


def test_what_a_second_planned_section_names_is_still_only_planned(repo):
    repo.write("DESIGN.md", DOC.replace("## Contracts", "## Planned\n\n- Another in `app/queue2.py`.\n\n## Contracts"))
    assert "missing-path" not in repo.occam("design", "check").stdout
    assert "planned, not built" in repo.occam("design", "for", "app/queue.py").stdout


def test_a_very_long_line_cannot_stall_the_hook():
    started = time.monotonic()
    design.parse(DOC.replace("## Problem\n", "## a" + " " * 200000 + "b\n\n## Problem\n"))
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("line", ["<!-- toc -->", "<details>", "</details>", '<img src="a.png">', "<https://example.com/x> is the tracker."])
def test_html_is_not_mistaken_for_template_text(repo, line):
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.", f"Shops lose orders.\n\n{line}"))
    assert "placeholder" not in repo.occam("design", "check").stdout


def test_template_text_is_still_caught(repo):
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.", "<Who has what problem, why now, and how much it's worth spending on.>"))
    assert "placeholder" in repo.occam("design", "check").stdout


@pytest.mark.parametrize("line, owner", [
    ("Owner: jane.doe. Verified 2026-01-01 against 0000000.", "jane.doe"),
    ("Owner: Dr. Ada Lovelace.", "Dr. Ada Lovelace"),
    ("Owner: Sam. Not yet verified against a commit.", "Sam"),
    ("Owner: <the person accountable for this file>. Not yet verified against a commit.", "not named"),
])
def test_the_owner_is_read_whole(repo, line, owner):
    repo.write("DESIGN.md", DOC.replace("Owner: Sam. Verified 2026-01-01 against 0000000.", line))
    assert repo.occam("design", "for", "other.py").stdout.startswith(f"DESIGN.md, owner {owner}. ")


def test_mentioning_supersedes_in_passing_retires_nothing():
    assert "use-cents" in _decision_ids(DOC + "- 2026-02-01 talk [accepted] We discussed Supersedes: `use-cents` and kept it. Why: y.\n")


def test_a_superseding_cycle_is_a_problem(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 aa [accepted] A. Why: y. Supersedes: `bb`.\n- 2026-02-02 bb [accepted] B. Why: y. Supersedes: `aa`.\n- 2026-02-03 me [accepted] M. Why: y. Supersedes: `me`.\n")
    done = repo.occam("design", "check")
    assert done.returncode == 1 and done.stdout.count("supersedes-cycle") == 3


def test_a_proposal_someone_replaced_is_not_shown_as_open(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 yes-queue [accepted] Queue it. Why: y. Applies: `app/billing.py`. Supersedes: `maybe-queue`.\n")
    assert "proposed, not decided" not in repo.occam("design", "for", "app/billing.py").stdout


def test_a_decision_is_about_what_it_applies_to_not_what_its_reason_names(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 fresh [accepted] Text. Why: the bug was in `other.py`, which we left alone. Applies: `app/retry.py`.\n")
    assert "fresh" not in repo.occam("design", "for", "other.py").stdout
    assert "fresh" in repo.occam("design", "for", "app/retry.py").stdout


def test_for_warns_when_the_document_is_broken(repo):
    repo.write("DESIGN.md", DOC.replace("## Decisions", "```\n## Decisions"))
    out = repo.occam("design", "for", "app/billing.py").stdout
    assert "design check" in out and "problem" in out


def test_for_a_folder_covers_what_is_cited_inside_it(repo):
    out = repo.occam("design", "for", "app").stdout
    assert "use-cents" in out and "Routes live" in out


def test_for_from_outside_with_root(repo, tmp_path):
    done = subprocess.run([sys.executable, str(design_tool()), "design", "for", "./app/billing.py", "--root", str(repo.path)], cwd=tmp_path, env=repo.env, capture_output=True, text=True)
    assert "use-cents" in done.stdout


def test_for_from_a_subfolder_takes_either_form(repo):
    for given in ("billing.py", "app/billing.py"):
        done = subprocess.run([sys.executable, str(design_tool()), "design", "for", given], cwd=repo.path / "app", env=repo.env, capture_output=True, text=True)
        assert "use-cents" in done.stdout, given


def test_for_says_when_a_path_is_outside(repo):
    assert "outside this project" in repo.occam("design", "for", "/etc/hosts").stdout


def test_a_doc_in_docs_can_cite_from_where_it_sits(repo):
    repo.git("rm", "-q", "--cached", "DESIGN.md")
    (repo.path / "DESIGN.md").unlink()
    repo.write("docs/DESIGN.md", DOC.replace("`app/billing.py`", "`../app/billing.py`"))
    assert "use-cents" in repo.occam("design", "for", "app/billing.py").stdout


def test_non_goals_and_open_questions_may_name_what_does_not_exist(repo):
    repo.write("DESIGN.md", DOC.replace("- Multi-currency.", "- Multi-currency, so no `app/fx.py`.").replace("## Decisions", "## Open questions\n\n- Should `app/cache.py` exist?\n\n## Decisions"))
    assert "missing-path" not in repo.occam("design", "check").stdout


def test_a_file_moved_elsewhere_is_not_found_by_its_tail(repo):
    repo.write("legacy/app/billing.py", "print(1)\n")
    (repo.path / "app/billing.py").unlink()
    assert "`app/billing.py`" in repo.occam("design", "check").stdout


@pytest.mark.parametrize("lines, flagged", [(200, False), (201, True)])
def test_the_length_limit_counts_lines_as_wc_does(repo, lines, flagged):
    padding = lines - DOC.count("\n")
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.\n", "Shops lose orders.\n" + "line\n" * padding))
    out = repo.occam("design", "check").stdout
    assert f"DESIGN.md, {lines} lines" in out and ("too-long" in out) is flagged


def test_a_route_in_backticks_does_not_silence_drift(repo):
    _verified(repo, DOC.replace("Shops lose orders.", "Shops lose orders at `/api/orders` and `https://x.test/y.py` and `../up/x.py`."))
    repo.write("app/billing.py", "print(2)\n")
    repo.commit()
    assert "commit since" in repo.occam("design", "check").stdout


def test_a_file_deleted_and_restored_is_not_called_gone(repo):
    _verified(repo)
    (repo.path / "app/billing.py").unlink()
    repo.commit()
    repo.write("app/billing.py", "print(1)\n")
    repo.commit()
    out = repo.occam("design", "check").stdout
    assert "Renamed or deleted" not in out and "commits since" in out


def test_only_the_header_says_when_it_was_verified(repo):
    head = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.write("DESIGN.md", DOC.replace("Owner: Sam. Verified 2026-01-01 against 0000000.", "Owner: Sam.") + f"- 2026-02-01 fresh [accepted] Verified 2026-01-01 against {head} once. Why: y.\n")
    assert "No `Verified" in repo.occam("design", "check").stdout


def test_a_branch_name_can_be_what_it_was_verified_against(repo):
    repo.git("branch", "checked")
    repo.write("DESIGN.md", DOC.replace("against 0000000", "against checked"))
    repo.write("app/billing.py", "print(2)\n")
    repo.commit()
    assert "commit since checked" in repo.occam("design", "check").stdout


def test_a_verified_commit_off_this_line_of_history_is_said(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("other.py", "print(5)\n")
    repo.commit()
    side = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.git("checkout", "-q", "main")
    repo.write("DESIGN.md", DOC.replace("against 0000000", f"against {side}"))
    repo.commit()
    assert "isn't an ancestor" in repo.occam("design", "check").stdout


def test_two_documents_are_named(repo):
    repo.write("docs/DESIGN.md", DOC)
    assert "docs/DESIGN.md" in repo.occam("design", "check").stdout


def test_check_says_when_it_could_not_read(repo):
    (repo.path / "DESIGN.md").write_bytes(b"\x00\x01binary")
    done = repo.occam("design", "check")
    assert done.returncode == 2 and "NOT CHECKED" in done.stdout


def test_a_list_item_right_above_the_heading_is_not_a_decision():
    parsed = design.parse(DOC.replace("\n\n## Decisions", "\n- A contract item right above.\n## Decisions"))
    assert parsed.malformed == []


def test_a_proposal_cannot_close_a_cycle(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 aa [proposed] A. Why: y. Supersedes: `bb`.\n- 2026-02-02 bb [accepted] B. Why: y. Supersedes: `aa`.\n")
    assert "supersedes-cycle" not in repo.occam("design", "check").stdout


def test_for_with_no_document_is_not_a_failure(tmp_path):
    state = tmp_path / "state"
    plain = tmp_path / "plain"
    plain.mkdir()
    done = Repo(plain, state).occam("design", "for", "x.py")
    assert done.returncode == 0 and "No design doc" in done.stdout


def test_for_the_root_covers_everything_cited(repo):
    out = repo.occam("design", "for", ".").stdout
    assert "use-cents" in out and "Routes live" in out
    assert "Routes live" not in repo.occam("design", "for", "app/retry.py").stdout


def test_title_case_headings_are_the_sections_they_look_like(repo):
    out = _hand_written(repo)
    assert "missing-section" not in out
    assert "Rewrite in" in repo.occam("design", "for", "app/billing.py").stdout


def test_two_spellings_of_a_section_are_one_section_twice():
    assert design.parse("## Non-goals\n\nx\n\n## non goals\n\ny\n").sections.keys() == {"Non-goals"}


def test_a_bold_owner_is_still_named(repo):
    _hand_written(repo)
    assert "owner Sam Reyes." in repo.occam("design", "for", "app/billing.py").stdout


def test_things_shaped_like_paths_that_are_not_ours_say_nothing(repo):
    out = _hand_written(repo)
    for name in ("net/http.Client", "encoding/json.Marshal", "gopkg.in/yaml.v3", "origin/release-1.2", "python/3.9", "application/vnd.api+json", "~/.ssh/id_rsa.pub", "~/.config/pay.json", "ghcr.io/acme/pay.v2", "@acme/pay.js"):
        assert f"missing-path: `{name}`" not in out
    assert "NOT CHECKED: `@acme/pay.js`" in out and "and 2 more. These could be paths or names" in out


def test_only_sections_saying_what_exists_are_checked_against_the_code(repo):
    out = _hand_written(repo)
    for name in ("rust/lib.rs", "queue/kafka.py", "app/refunds/core.py", "old/floats.py"):
        assert f"`{name}`" not in out


def test_a_file_moved_under_another_folder_is_still_caught(repo):
    repo.write("src/app/moved.py", "x = 1\n")
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`", "- Billing lives in `app/moved.py`"))
    assert "`app/moved.py` isn't at that path" in repo.occam("design", "check").stdout


def test_a_retired_decision_on_nothing_is_not_a_lead(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 lost [accepted] Do it. Why: y. Applies: `Gonefile`.\n- 2026-02-02 kept [accepted] Do it. Why: y. Supersedes: `lost`.\n")
    assert "Gonefile" not in repo.occam("design", "check").stdout


def test_everywhere_lists_say_when_they_stop(repo):
    many = "".join(f"- 2026-02-01 d{number} [accepted] Do it. Why: y.\n" for number in range(10))
    repo.write("DESIGN.md", DOC + many)
    out = repo.occam("design", "for", "app/billing.py").stdout
    assert "d7 [accepted]" in out and "d8 [accepted]" not in out and "and 2 more in the document." in out


@stock_only
def test_a_citation_too_long_for_the_system_does_not_crash(repo):
    long = "a" * 300 + "/b.py"
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", f"- Odd: `{long}`.") + f"- 2026-02-01 too-long [accepted] Do it. Why: y. Applies: `{long}`.\n")
    done = _stock(repo, "design", "check")
    assert "Traceback" not in done.stderr, done.stderr


def test_a_wrapped_line_keeps_its_sentence(repo):
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.\n- Routes live in `app/web/`.", "It does NOT\nhandle `app/billing.py` at all.\n\n- A list item\n  with `app/web/` wrapped.\n- Another item."))
    out = repo.occam("design", "for", "app/billing.py").stdout
    assert "now: It does NOT handle `app/billing.py` at all." in out
    out = repo.occam("design", "for", "app/web/routes.py").stdout
    assert "now: - A list item with `app/web/` wrapped." in out and "Another item" not in out


def test_a_commented_out_decision_is_not_in_force(repo):
    repo.write("DESIGN.md", DOC + "<!--\n- 2020-01-01 commented [accepted] Old. Why: y. Applies: `app/billing.py`.\n-->\n")
    assert "commented" not in repo.occam("design", "for", "app/billing.py").stdout
    assert "2 decisions in force" in repo.occam("design", "check").stdout


def test_a_heading_in_a_comment_is_not_a_section():
    assert len(design.parse("## Decisions\n\n<!--\n## Decisions\n-->\n").sections["Decisions"]) == 1


def test_a_lowercase_file_is_not_the_document(tmp_path):
    (tmp_path / "design.md").write_text(DOC)
    assert design.find(tmp_path) is None


def test_an_owner_in_angle_brackets_is_named(repo):
    repo.write("DESIGN.md", DOC.replace("Owner: Sam.", "Owner: <alice@example.com>."))
    assert "placeholder" not in repo.occam("design", "check").stdout
    assert "owner <alice@example.com>." in repo.occam("design", "for", "app/billing.py").stdout


def test_the_template_owner_is_still_a_placeholder(repo):
    repo.write("DESIGN.md", DOC.replace("Owner: Sam.", "Owner: <the person accountable for this file>."))
    assert "placeholder" in repo.occam("design", "check").stdout
    assert "owner not named" in repo.occam("design", "for", "app/billing.py").stdout


@pytest.mark.parametrize("line", ["Verified 2026-01-01 against `abc123`.", "Verified 2026-01-01 against commit abc123."])
def test_common_spellings_of_the_verified_line(line):
    assert design._PROVENANCE.search(line).group(2) == "abc123"


def test_a_citation_beside_a_document_in_docs_is_not_missing(repo):
    repo.git("rm", "-q", "--cached", "DESIGN.md")
    (repo.path / "DESIGN.md").unlink()
    repo.write("docs/images/x.png", "x")
    repo.write("docs/DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Diagram: `./images/x.png`."))
    assert "images/x.png" not in repo.occam("design", "check").stdout


def test_output_counts_one_as_one(repo):
    repo.write("DESIGN.md", DOC.replace("- 2026-01-01 use-cents [accepted] Money is integer cents. Why: floats lost pennies. Applies: `app/billing.py`.\n", ""))
    out = repo.occam("design", "check").stdout
    assert "1 decision in force, 0 problems." in out


@stock_only
def test_a_deleted_citation_under_an_unreadable_folder_does_not_crash(repo):
    repo.write("locked/x.py", "x = 1\n")
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Locked: `locked/x.py`."))
    repo.commit()
    head = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.git("rm", "-q", "locked/x.py")
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Locked: `locked/x.py`.").replace("0000000", head))
    repo.commit()
    (repo.path / "locked").mkdir()
    (repo.path / "locked").chmod(0)
    try:
        done = _stock(repo, "design", "check")
        assert "Traceback" not in done.stderr, done.stderr
    finally:
        (repo.path / "locked").chmod(0o755)


@pytest.mark.parametrize("named_root", [False, True])
def test_a_deleted_working_folder_is_not_a_crash(repo, tmp_path, named_root):
    gone = tmp_path / "gone"
    gone.mkdir()
    root = f' --root "{repo.path}"' if named_root else ""
    script = f'cd "{gone}" && rmdir "{gone}" && exec "{sys.executable}" "{design_tool()}" design for app/billing.py{root}'
    done = subprocess.run(["sh", "-c", script], env=repo.env, capture_output=True, text=True)
    assert "Traceback" not in done.stderr and done.returncode == 2 and "no longer exists" in done.stdout


def test_a_terminal_that_cannot_show_the_document_is_not_a_crash(repo):
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.", "- Billing → lives in `app/billing.py`."))
    done = subprocess.run([sys.executable, str(design_tool()), "design", "for", "app/billing.py"], cwd=repo.path, env={**repo.env, "PYTHONIOENCODING": "ascii"}, capture_output=True, text=True)
    assert "Traceback" not in done.stderr and "Billing ? lives" in done.stdout


def test_a_root_named_outright_is_that_folder(tmp_path):
    parent = tmp_path / "parent"
    project = parent / "project"
    project.mkdir(parents=True)
    (parent / ".gitignore").write_text("")
    (project / "DESIGN.md").write_text(DOC)
    assert "use-cents" in Repo(project, tmp_path / "state").occam("design", "for", "app/billing.py", "--root", str(project)).stdout


@pytest.mark.parametrize("cwd_below", [False, True])
def test_the_pointer_works_as_printed(tmp_path, monkeypatch, cwd_below):
    monkeypatch.syspath_prepend(str(ROOT / "plugin" / "hooks"))
    import design_notes
    project = tmp_path / "my project"
    (project / "sub").mkdir(parents=True)
    (project / "app").mkdir()
    (project / "app" / "billing.py").write_text("print(1)\n")
    (project / "DESIGN.md").write_text(DOC)
    (tmp_path / ".gitignore").write_text("")  # a marker above, so the tool alone would look there
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    cwd = project / "sub" if cwd_below else project
    command = re.search(r"`(python3 .*?)`", design_notes.session_note(str(cwd))).group(1).replace("<path>", "app/billing.py")
    words = shlex.split(command)
    words[0] = sys.executable
    done = subprocess.run(words, cwd=cwd, env=Repo(project, tmp_path / "state").env, capture_output=True, text=True)
    assert "use-cents" in done.stdout, done.stdout + done.stderr


def test_naming_comment_markers_apart_hides_nothing(repo):
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.", "Output strips `<!--` openers.").replace("- `app/billing.py` returns cents as an integer.", "- `app/billing.py` returns cents. The closer is `-->`."))
    out = repo.occam("design", "check").stdout
    assert "missing-section" not in out and "0 problems" in out
    assert "now: - Billing lives" in repo.occam("design", "for", "app/billing.py").stdout


def test_an_opener_named_alone_hides_nothing(repo):
    repo.write("DESIGN.md", DOC.replace("Shops lose orders.", "Output strips `<!--` markers."))
    assert "use-cents" in repo.occam("design", "for", "app/billing.py").stdout


def test_an_unclosed_comment_is_a_problem_not_a_silence(repo):
    repo.write("DESIGN.md", DOC.replace("- 2026-01-04 maybe-queue", "<!-- a note, never closed\n- 2026-01-04 maybe-queue"))
    done = repo.occam("design", "check")
    assert done.returncode == 1 and "unclosed-comment" in done.stdout
    assert "may be incomplete" in repo.occam("design", "for", "app/billing.py").stdout


def test_no_document_can_make_parsing_slow():
    started = time.monotonic()
    design.parse(DOC + "x <!-- " * 40000 + "\n" + "<!-- x\n" * 40000)
    assert time.monotonic() - started < 3


def test_a_table_row_is_quoted_alone(repo):
    table = "| Part | Path |\n|---|---|\n| web | `app/web/` |\n| billing | `app/billing.py` |"
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.\n- Routes live in `app/web/`.", table))
    out = repo.occam("design", "for", "app/billing.py").stdout
    assert "now: | billing | `app/billing.py` |\n" in out and "| web |" not in out


def test_a_long_paragraph_is_quoted_around_what_was_asked(repo):
    paragraph = "Background that goes on. " * 30 + "\n`app/billing.py` does NOT round cents."
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.\n- Routes live in `app/web/`.", paragraph))
    out = repo.occam("design", "for", "app/billing.py").stdout
    line = next(line for line in out.split("\n") if line.startswith("  now:"))
    assert "`app/billing.py` does NOT round cents." in line and "now: ..." in line and len(line) < design.MAX_NOTE + 20


def test_subheadings_do_not_run_together(repo):
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.\n- Routes live in `app/web/`.", "### Billing\nIn `app/billing.py`.\n### Retry\nIn `app/retry.py`."))
    out = repo.occam("design", "for", "app/retry.py").stdout
    assert "now: In `app/retry.py`." in out and "billing.py" not in out


def test_commands_and_foreign_folders_are_not_called_missing(repo):
    names = ("pytest tests/", "ruff check src/", "~/.config/", "net/http/", "origin/", "@types/", "$HOME/bin/", "image/*", "api/v1/*", "width * 2 / 3")
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Odds: " + ", ".join(f"`{name}`" for name in names) + "."))
    out = repo.occam("design", "check").stdout
    assert "missing-path" not in out, out


def test_a_folder_with_brackets_is_read_literally(repo):
    repo.write("pages/[id]/page.tsx", "x\n")
    repo.write("DESIGN.md", DOC + "- 2026-02-01 route [accepted] R. Why: y. Applies: `pages/[id]`.\n")
    assert "route applies" not in repo.occam("design", "check").stdout
    assert "route [accepted]" in repo.occam("design", "for", "pages/[id]/page.tsx").stdout


@pytest.mark.parametrize("clause", ["Applies: app/billing.py.", "Applies: `app/*.py`."])
def test_an_applies_it_cannot_read_is_a_problem_not_everywhere(repo, clause):
    repo.write("DESIGN.md", DOC + f"- 2026-02-01 unread [accepted] U. Why: y. {clause}\n")
    assert "unreadable-applies" in repo.occam("design", "check").stdout
    assert "Decisions on no particular file" not in repo.occam("design", "for", "app/retry.py").stdout


@pytest.mark.parametrize("line", ["* 2026-02-01 star [accepted] S. Why: y.", "  - 2026-02-01 indented [accepted] I. Why: y.", "  Applies: `app/billing.py`."])
def test_what_looks_like_a_decision_and_is_not_says_so(repo, line):
    repo.write("DESIGN.md", DOC + line + "\n")
    assert "malformed-decision" in repo.occam("design", "check").stdout


def test_a_supersedes_that_retires_nothing_says_so(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 twisted [accepted] T. Why: y. Supersedes: `use-cents`. Applies: `app/billing.py`.\n")
    assert "misplaced-supersedes" in repo.occam("design", "check").stdout


def test_a_decision_on_nothing_is_a_lead(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 lost [accepted] Do it. Why: y. Applies: `Gonefile`.\n")
    assert "lost applies to `Gonefile`" in repo.occam("design", "check").stdout


def test_check_says_what_it_could_not_tell(repo):
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Gone: `oldstuff/core`, `app/gone file.py`, `oldfolder/`, `routes/$slug.tsx`."))
    out = repo.occam("design", "check").stdout
    unchecked = next(line for line in out.split("\n") if "NOT CHECKED" in line)
    for name in ("oldstuff/core", "app/gone file.py", "oldfolder", "routes/$slug.tsx"):
        assert f"`{name}`" in unchecked


def test_a_name_inside_a_reported_path_is_still_listed(repo):
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Odd: `pay/core` and `gone/pay/core.py`."))
    out = repo.occam("design", "check").stdout
    assert "`gone/pay/core.py` doesn't exist here" in out and "`pay/core`" in next(line for line in out.split("\n") if "NOT CHECKED" in line)


@pytest.mark.parametrize("ref", ["HEAD", "main"])
def test_verified_against_something_that_moves_says_so(repo, ref):
    repo.write("DESIGN.md", DOC.replace("0000000", ref))
    assert "moves with every commit" in repo.occam("design", "check").stdout


def test_a_long_list_of_deletions_says_when_it_stops(repo):
    names = [f"app/gone{number}.py" for number in range(11)]
    for name in names:
        repo.write(name, "print(1)\n")
    cited = DOC.replace("- Routes live in `app/web/`.", "- Also " + ", ".join(f"`{name}`" for name in names) + ".")
    repo.write("DESIGN.md", cited)
    repo.commit()
    head = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.git("rm", "-q", *names)
    repo.write("DESIGN.md", cited.replace("0000000", head))
    repo.commit()
    assert " and 3 more." in repo.occam("design", "check").stdout


def test_a_bold_owner_line_loses_its_markers(repo):
    repo.write("DESIGN.md", DOC.replace("Owner: Sam.", "**Owner: Sam**\n\n"))
    assert "owner Sam." in repo.occam("design", "for", "app/billing.py").stdout


def test_a_closed_heading_is_the_section():
    assert "Decisions" in design.parse("## Decisions ##\n").sections


def test_a_line_and_column_are_not_part_of_the_path():
    assert design._cited("See `app/retry.py:10:5` and `app/a.py:3-9`.") == ["app/retry.py", "app/a.py"]


@stock_only
def test_a_name_too_long_for_the_system_is_not_called_outside(repo):
    done = _stock(repo, "design", "for", "a" * 300 + ".py")
    assert "Traceback" not in done.stderr and "outside this project" not in done.stdout


def test_a_huge_span_of_locations_is_not_slow():
    started = time.monotonic()
    assert design._cited("`" + ":1" * 100000 + "x`") == []
    assert time.monotonic() - started < 1


def test_a_line_of_backticks_is_not_slow():
    started = time.monotonic()
    design.parse(DOC + "`" * 199000 + "x `\n")
    assert time.monotonic() - started < 3


def test_an_inline_triple_backtick_still_opens_no_block():
    assert "after" in design.parse("```x``` inline\nafter\n").prose


def test_naming_an_opener_in_what_is_checked_hides_nothing_from_the_check(repo):
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Comments open with `<!--` in Markdown.\n\nThe parser is `app/gone.py`.\nA dead [link](nowhere.md)."))
    out = repo.occam("design", "check").stdout
    assert "missing-path: `app/gone.py`" in out and "nowhere.md" in out


def test_a_real_comment_in_what_is_checked_is_not_checked(repo):
    repo.write("DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "<!--\n- Old: `app/gone.py`.\n-->"))
    assert "app/gone.py" not in repo.occam("design", "check").stdout


@pytest.mark.parametrize("clause", ["Applies: `app/*.py`, `app/billing.py`.", "Applies: app/retry.py, `app/billing.py`.", "Applies:`app/billing.py`.", "applies: `app/billing.py`.", "Applies: `app/billing.py`. Why: `app/retry.py` depends on it."])
def test_an_applies_it_cannot_read_in_full_is_a_problem(repo, clause):
    repo.write("DESIGN.md", DOC + f"- 2026-02-01 half [accepted] H. Why: y. {clause}\n")
    assert "unreadable-applies" in repo.occam("design", "check").stdout
    assert "Decisions on no particular file" not in repo.occam("design", "for", "other.py").stdout


def test_a_reason_after_applies_governs_nothing(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 only [accepted] Only b. Applies: `app/billing.py`. Why: `app/retry.py` must not change.\n")
    assert "only [accepted]" not in repo.occam("design", "for", "app/retry.py").stdout


def test_two_paths_and_a_supersedes_all_read(repo):
    repo.write("DESIGN.md", DOC + "- 2026-02-01 both [accepted] B. Why: y. Applies: `app/billing.py`, `app/retry.py`. Supersedes: `use-cents`.\n")
    parsed = design.parse((repo.path / "DESIGN.md").read_text())
    assert design._applies(parsed.decisions[-1]) == ["app/billing.py", "app/retry.py"] and parsed.decisions[-1].supersedes == "use-cents"
    assert "unreadable-applies" not in repo.occam("design", "check").stdout


@pytest.mark.parametrize("extra", ["2026-01-05 use-pg [accepted] Use Postgres. Why: x.", "| a | b |", "### Use Kafka", "- 2026-01-05 wrap [accepted] Long text that wraps\nonto the next line. Why: x."])
def test_what_a_reader_would_take_for_a_decision_says_it_is_not(repo, extra):
    repo.write("DESIGN.md", DOC + extra + "\n")
    assert "malformed-decision" in repo.occam("design", "check").stdout


def test_an_opening_paragraph_in_decisions_is_fine(repo):
    repo.write("DESIGN.md", DOC.replace("## Decisions\n\n", "## Decisions\n\nAppend only.\nSupersede rather than rewrite.\n\n"))
    assert "malformed-decision" not in repo.occam("design", "check").stdout


def test_a_table_in_decisions_before_any_decision_says_it_is_not_one(repo):
    repo.write("DESIGN.md", DOC.split("## Decisions")[0] + "## Decisions\n\n| a | b |\n")
    assert "malformed-decision" in repo.occam("design", "check").stdout


def test_a_symlink_loop_as_root_is_not_a_crash(repo):
    (repo.path / "loop").symlink_to("loop")
    done = _stock(repo, "design", "check", "--root", "loop") if STOCK_PYTHON.exists() else repo.occam("design", "check", "--root", "loop")
    assert "Traceback" not in done.stderr and done.returncode == 2


def test_drift_from_a_subfolder_root_reads_paths_from_there(repo):
    repo.write("sub/old.py", "x = 1\n")
    repo.write("sub/DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Old: `old.py`."))
    repo.commit()
    head = repo.git("rev-parse", "--short", "HEAD").strip()
    repo.write("sub/DESIGN.md", DOC.replace("- Routes live in `app/web/`.", "- Old: `old.py`.").replace("0000000", head))
    repo.git("rm", "-q", "sub/old.py")
    repo.commit()
    repo.write("sub/old.py", "x = 1\n")
    repo.commit()
    assert "Renamed or deleted" not in repo.occam("design", "check", "--root", str(repo.path / "sub")).stdout


def test_an_empty_comment_is_closed():
    assert "after" in design.parse("<!-->\nafter\n").prose and not design.parse("<!--->\nafter\n").open_comment


def test_a_clip_finds_the_citation_not_a_word_containing_it():
    line = "rapid " * 100 + "`api/` is the part asked about, and " + "more " * 100
    assert "`api/`" in design.clip(line, "api")
