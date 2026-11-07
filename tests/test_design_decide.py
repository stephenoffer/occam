"""The shared design doc's one write: `occam design decide` appends a single line, or refuses."""

import multiprocessing
import os
import subprocess
import sys

import pytest

from design_support import DOC, _decide, design, design_tool

pytest_plugins = ("design_support",)  # its `repo` and `agent` fixtures


def test_decide_appends_a_line_that_parses(repo):
    done = repo.occam("design", "decide", "no-floats", "Never store floats", "--why", "they round", "--applies", "app/billing.py")
    assert done.returncode == 0
    added = design.parse((repo.path / "DESIGN.md").read_text()).decisions[-1]
    assert added.id == "no-floats" and added.status == "accepted" and "Why: they round" in added.text and "`app/billing.py`" in added.text
    assert "no-floats" in repo.occam("design", "for", "app/billing.py").stdout


def test_decide_can_propose_and_supersede(repo):
    repo.occam("design", "decide", "maybe", "Use a queue", "--why", "spikes", "--proposed")
    repo.occam("design", "decide", "cents-2", "Use micros", "--why", "fees", "--supersedes", "use-cents", "--applies", "app/billing.py")
    parsed = design.parse((repo.path / "DESIGN.md").read_text())
    active = [decision.id for decision in design.in_force(parsed)]
    assert "maybe" not in active and "use-cents" not in active and "cents-2" in active


@pytest.mark.parametrize("args, message", [
    (["use-cents", "Again", "--why", "x"], "already taken"),
    (["Bad_ID", "Text", "--why", "x"], "isn't usable"),
    (["fresh", "Text", "--why", "x", "--supersedes", "nope"], "Nothing here is called"),
    (["fresh", "Text"], "Usage"),
    (["fresh", "Text\nInjected", "--why", "x"], "one line"),
])
def test_decide_refuses_what_would_corrupt_the_record(repo, args, message):
    before = (repo.path / "DESIGN.md").read_text()
    done = repo.occam("design", "decide", *args)
    assert done.returncode == 2 and message in done.stdout
    assert (repo.path / "DESIGN.md").read_text() == before


def test_decide_refuses_if_appending_would_land_in_the_wrong_section(repo):
    repo.write("DESIGN.md", DOC + "\n## Later\n\nText.\n")
    assert "last section" in repo.occam("design", "decide", "fresh", "Text", "--why", "x").stdout


def test_decide_handles_a_file_with_no_final_newline(repo):
    repo.write("DESIGN.md", DOC.rstrip("\n"))
    repo.occam("design", "decide", "fresh", "Text", "--why", "x")
    assert [decision.id for decision in design.parse((repo.path / "DESIGN.md").read_text()).decisions][-2:] == ["maybe-queue", "fresh"]


def test_parallel_writers_lose_nothing(tmp_path):
    (tmp_path / "DESIGN.md").write_text(DOC)
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        codes = pool.map(_decide, [(str(tmp_path), index) for index in range(24)])
    assert codes == [0] * 24
    parsed = design.parse((tmp_path / "DESIGN.md").read_text())
    assert not parsed.malformed and sum(decision.id.startswith("parallel-") for decision in parsed.decisions) == 24


def test_an_unclosed_fence_is_named_and_stops_decide(repo):
    repo.write("DESIGN.md", DOC + "```\nforgotten\n")
    done = repo.occam("design", "check")
    assert done.returncode == 1 and "unclosed-fence" in done.stdout
    before = (repo.path / "DESIGN.md").read_text()
    assert repo.occam("design", "decide", "fresh", "Text", "--why", "x").returncode == 2
    assert (repo.path / "DESIGN.md").read_text() == before


def test_decide_keeps_a_crlf_file_crlf(repo):
    (repo.path / "DESIGN.md").write_bytes(DOC.replace("\n", "\r\n").encode())
    assert repo.occam("design", "decide", "fresh", "Text", "--why", "x").returncode == 0
    raw = (repo.path / "DESIGN.md").read_bytes()
    assert raw.endswith(b"Why: x.\r\n") and b"\n" not in raw.replace(b"\r\n", b"")


@pytest.mark.parametrize("args", [
    ["talk", "Say Supersedes: `use-cents` here", "--why", "y"],
    ["talk", "Text", "--why", "Supersedes: `use-cents`"],
    ["talk", "Text", "--why", "See Applies: `other.py`"],
])
def test_decide_refuses_a_field_that_would_read_as_another_field(repo, args):
    before = (repo.path / "DESIGN.md").read_text()
    assert repo.occam("design", "decide", *args).returncode == 2
    assert (repo.path / "DESIGN.md").read_text() == before


@pytest.mark.parametrize("args", [
    ["fresh", "Real\r- 2026-01-01 forged [accepted] Forged. Why: f. Applies: `other.py`", "--why", "y"],
    ["fresh", "Text", "--why", "y", "--applies", "x.py\n## After\n\n- 2026-01-01 forged [accepted] Forged. Why: f."],
    ["abc\n", "Text", "--why", "y"],
    ["fresh", "Line separator", "--why", "y"],
    ["fresh", "Bad\udc85bytes", "--why", "y"],
    ["fresh", "Use `x for it", "--why", "y", "--applies", "other.py"],
    ["fresh", "Text", "--why", "y", "--applies", "a`b.py"],
    ["fresh", "...", "--why", "..."],
])
def test_decide_refuses_what_could_forge_or_hide_a_record(repo, args):
    before = (repo.path / "DESIGN.md").read_text()
    done = repo.occam("design", "decide", *args)
    assert done.returncode == 2 and "Traceback" not in done.stderr
    assert (repo.path / "DESIGN.md").read_text() == before


@pytest.mark.parametrize("given", ["./other.py", "other.py", "OTHER_ABSOLUTE"])
def test_applies_is_recorded_from_the_root_whichever_way_it_was_given(repo, given):
    given = str(repo.path / "other.py") if given == "OTHER_ABSOLUTE" else given
    assert repo.occam("design", "decide", "fresh", "Text", "--why", "y", "--applies", given).returncode == 0
    assert "fresh" in repo.occam("design", "for", "other.py").stdout


def test_applies_outside_the_project_is_refused(repo):
    done = repo.occam("design", "decide", "fresh", "Text", "--why", "y", "--applies", "/etc/hosts")
    assert done.returncode == 2 and "outside" in done.stdout


def test_a_cited_path_with_a_space_can_be_found(repo):
    repo.write("my dir/x.py", "print(1)\n")
    assert repo.occam("design", "decide", "fresh", "Text", "--why", "y", "--applies", "my dir/x.py").returncode == 0
    assert "fresh" in repo.occam("design", "for", "my dir/x.py").stdout


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="permissions")
def test_a_file_it_cannot_write_is_said_plainly(repo, tmp_path):
    target = repo.path / "DESIGN.md"
    target.chmod(0o444)
    done = repo.occam("design", "decide", "fresh", "Text", "--why", "y")
    target.chmod(0o644)
    assert done.returncode == 2 and "Traceback" not in done.stderr and "Couldn't write" in done.stdout
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    sealed.chmod(0o555)
    done = repo.occam("design", "init", "--root", str(sealed))
    sealed.chmod(0o755)
    assert done.returncode == 2 and "Traceback" not in done.stderr and "Couldn't write" in done.stdout


def test_a_decision_can_apply_to_a_file_with_no_extension_or_a_folder(repo):
    repo.write("Makefile", "all:\n")
    for identifier, target in (("use-make", "Makefile"), ("all-of-app", "app"), ("app-slash", "app/")):
        done = repo.occam("design", "decide", identifier, "Do it", "--why", "because", "--applies", target)
        assert done.returncode == 0, done.stdout
    assert "use-make" in repo.occam("design", "for", "Makefile").stdout
    out = repo.occam("design", "for", "app/billing.py").stdout
    assert "all-of-app" in out and "app-slash" in out


def test_superseding_with_an_applies_keeps_the_id_out_of_the_paths(repo):
    done = repo.occam("design", "decide", "newer", "Do it", "--why", "because", "--applies", "Makefile", "--supersedes", "use-cents")
    assert done.returncode == 0, done.stdout
    decision = design.parse((repo.path / "DESIGN.md").read_text()).decisions[-1]
    assert design._applies(decision) == ["Makefile"] and decision.supersedes == "use-cents"


def test_applies_from_a_subfolder_means_what_it_can_only_mean(repo):
    repo.write("app/inner/keep.py", "x = 1\n")
    subfolder = repo.path / "app"
    for identifier, target, stored in (("from-root-new", "app/new.py", "app/new.py"), ("from-here-new", "new2.py", "app/new2.py"), ("from-here-real", "inner/keep.py", "app/inner/keep.py")):
        done = subprocess.run([sys.executable, str(design_tool()), "design", "decide", identifier, "Do it", "--why", "because", "--applies", target], cwd=subfolder, env=repo.env, capture_output=True, text=True)
        assert done.returncode == 0, done.stdout
        assert f"Applies: `{stored}`." in (repo.path / "DESIGN.md").read_text()


def test_decide_refuses_a_line_an_open_comment_would_hide(repo):
    before = DOC + "<!-- unfinished note\n"
    repo.write("DESIGN.md", before)
    done = repo.occam("design", "decide", "hidden", "Do it", "--why", "because")
    assert done.returncode == 2 and (repo.path / "DESIGN.md").read_text() == before


def test_decide_refuses_to_close_a_cycle(repo):
    before = DOC + "- 2026-02-01 later [accepted] L. Why: y. Supersedes: `not-yet`.\n"
    repo.write("DESIGN.md", before)
    done = repo.occam("design", "decide", "not-yet", "N", "--why", "because", "--supersedes", "later")
    assert done.returncode == 2 and (repo.path / "DESIGN.md").read_text() == before


def test_a_short_write_is_reported(repo, monkeypatch):
    monkeypatch.setattr(design.os, "write", lambda descriptor, data: 1)
    text, code = design.decide(repo.path, "short", "Do it", "because", [], False, None)
    assert code == 2 and "Only part of short" in text


def test_applies_can_hold_a_dollar_route(repo):
    repo.write("routes/$slug.tsx", "x\n")
    done = repo.occam("design", "decide", "slug", "Do it", "--why", "because", "--applies", "routes/$slug.tsx")
    assert done.returncode == 0, done.stdout
    assert "slug [accepted]" in repo.occam("design", "for", "routes/$slug.tsx").stdout


def test_a_mistyped_root_is_neither_a_clean_check_nor_a_write(repo, tmp_path):
    before = (repo.path / "DESIGN.md").read_text()
    for typo in (tmp_path / "typo", repo.path / "typo"):
        done = repo.occam("design", "check", "--root", str(typo))
        assert done.returncode == 2 and "No such folder" in done.stdout
        assert repo.occam("design", "decide", "viatypo", "Do it", "--why", "because", "--root", str(typo)).returncode == 2
    assert (repo.path / "DESIGN.md").read_text() == before


def test_a_comment_in_a_code_span_keeps_what_follows(repo):
    repo.write("DESIGN.md", DOC.replace("- Billing lives in `app/billing.py`.", "- Markers are `<!-- begin -->` in `app/billing.py`."))
    assert "now: - Markers are" in repo.occam("design", "for", "app/billing.py").stdout
    done = repo.occam("design", "decide", "strip", "Strip <!-- never --> early", "--why", "because", "--applies", "app/retry.py")
    assert done.returncode == 0, done.stdout
    assert "Strip <!-- never --> early" in repo.occam("design", "for", "app/retry.py").stdout


@pytest.mark.parametrize("applies", [("",), (".",), (".", "app"), ("app/*.py",)])
def test_decide_refuses_an_applies_it_cannot_record(repo, applies):
    before = (repo.path / "DESIGN.md").read_text()
    args = [word for path in applies for word in ("--applies", path)]
    assert repo.occam("design", "decide", "odd", "Do it", "--why", "because", *args).returncode == 2
    assert (repo.path / "DESIGN.md").read_text() == before


def test_no_applies_is_listed_as_applying_everywhere(repo):
    assert repo.occam("design", "decide", "everywhere", "Do it", "--why", "because").returncode == 0
    out = repo.occam("design", "for", "app/billing.py").stdout
    assert "Decisions on no particular file" in out and "everywhere [accepted]" in out
    assert "use-cents" not in out.split("Decisions on no particular file")[1]
