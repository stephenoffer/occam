"""The head-to-head harness can't leak its answer key, and it scores what a report really says. No model runs here."""

import audit_comparison
import score_audit


def test_the_answer_key_never_reaches_the_stage(tmp_path):
    stage = tmp_path / "stage"
    audit_comparison.build_stage(stage)
    assert (stage / "skills" / "occam-audit" / "SKILL.md").exists(), "the with-skill arm needs the real plugin"
    assert (stage / "evals" / "audit-blind" / "files" / "pyproject.toml").exists()
    names = {path.name for path in stage.rglob("*")}
    assert not names & {"ANSWERS.json", "DECOYS.json", "hidden", "solutions"}


def test_the_prompt_is_the_same_for_both_arms_and_names_no_skill():
    assert "occam" not in audit_comparison.PROMPT.lower()
    assert "AUDIT.md" in audit_comparison.PROMPT


def test_a_report_is_scored_by_where_it_points():
    answers = score_audit.json.loads((score_audit.FIXTURE / "ANSWERS.json").read_text())
    target = answers[0]
    hit = score_audit.score_report(f"- `{target['file']}:{target['line']}` is wrong because reasons\n")
    assert hit["located"] >= 1
    miss = score_audit.score_report("- nothing specific, the code seems risky in places\n")
    assert miss["located"] == 0 and miss["findings"] == 0


def test_a_report_citing_everything_is_visible_in_the_decoy_count():
    decoys = score_audit.json.loads((score_audit.FIXTURE / "DECOYS.json").read_text())
    report = "\n".join(f"{item['file']}:{item['line']} looks bad" for item in decoys)
    assert score_audit.score_report(report)["decoys_flagged"].split("/")[0] == str(len(decoys))
