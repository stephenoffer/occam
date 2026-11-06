"""The scenario spec is complete, honest about status, and the cases have not moved since the freeze."""

import hashlib
import re
from pathlib import Path

import pytest
import yaml

import freeze

EVALS = Path(__file__).resolve().parents[1] / "evals"
SCENARIOS = yaml.safe_load((EVALS / "scenarios.yaml").read_text())["scenarios"]
REQUIRED = {"id", "title", "status", "language", "risk", "task", "starting_state", "acceptance", "forbidden", "method"}
SKILLS_DIR = EVALS.parent / "plugin" / "skills"
SKILL_DIR = SKILLS_DIR / "occam"


def test_at_least_24_scenarios_with_unique_ids():
    ids = [scenario["id"] for scenario in SCENARIOS]
    assert len(ids) >= 24 and len(ids) == len(set(ids))


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
def test_scenario_is_fully_specified(scenario):
    assert not REQUIRED - scenario.keys()
    assert scenario["status"] in {"smoke", "holdout", "metric", "specified", "regression", "python", "hard"}


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s["status"] == "smoke"], ids=lambda s: s["id"])
def test_smoke_scenarios_point_at_a_real_case(scenario):
    assert (EVALS / "cases" / "smoke" / scenario["case"] / "prompt.md").exists()


def test_multiple_languages_and_risk_levels():
    runnable = [s for s in SCENARIOS if s["status"] in {"smoke", "holdout"}]
    assert {"python", "javascript", "sql"} <= {s["language"] for s in runnable}
    assert {"small", "standard", "high"} <= {s["risk"] for s in runnable}


def test_trigger_suite_has_both_polarities():
    tags = [(p / "prompt.md").read_text().split("---")[1] for p in (EVALS / "cases" / "triggers").iterdir() if (p / "prompt.md").exists()]
    assert sum("positive" in t for t in tags) >= 10
    assert sum("negative" in t for t in tags) >= 10


def prompt_body(case: Path) -> str:
    return (case / "prompt.md").read_text().split("---", 2)[2].lower()


def test_blind_prompts_do_not_leak_their_diagnosis():
    for suite in ("holdout", "regression", "python", "hard"):
        terms = yaml.safe_load((EVALS / "cases" / suite / "LEAK_TERMS.yaml").read_text())
        # A prompt has to be able to name its own entry point, so a term that is part of the case's name is fine.
        leaks = {case: [t for t in case_terms if t.lower() in prompt_body(EVALS / "cases" / suite / case) and t.lower() not in case]
                 for case, case_terms in terms.items()}
        assert not any(leaks.values()), f"a {suite} prompt contains its diagnosis terms (names hidden to preserve blinding)"


# Identifiers and phrases specific to smoke fixtures. The skill must teach general judgment, not these answers.
SMOKE_TERMS = ["to_url_token", "round_invoice_total", "round_display_amount", "get_invoices", "nextpagetoken",
               "vendor_sandbox", "fake_vendor", "logmerge", "ledgerkit", "bulkfetch", "crmsync", "stockreport",
               "enrich_record", "loyalty", "review-checkin", "reviewer-metrics", "requiresignature", "access_log"]


# Holdout list entries a blinded adjudicator judged to be generic vocabulary, by hash so the skill author stays blind.
GENERIC_OVERLAP_SHA256 = {"e484eeb74a6fcc28e739cc8629bcb7475f9a465df8b420228ea14efb67027723"}
# s47 tests the same APIs and sinks the guidance names, so this case's list overlaps it by design: a blinded adjudicator found
# 23 of 41 terms in the guidance, all generic. A case-level exception keeps the exemption above from weakening other cases.
ABOUT_THE_GUIDANCE_TOPIC = {"partner-meter-backfill"}


@pytest.mark.skipif(not SKILL_DIR.exists(), reason="skill not written yet")
def test_skill_contains_no_case_specific_terms():
    blind = {**yaml.safe_load((EVALS / "cases" / "holdout" / "LEAK_TERMS.yaml").read_text()),
             **yaml.safe_load((EVALS / "cases" / "regression" / "LEAK_TERMS.yaml").read_text()),
             **yaml.safe_load((EVALS / "cases" / "python" / "LEAK_TERMS.yaml").read_text()),
             **yaml.safe_load((EVALS / "cases" / "hard" / "LEAK_TERMS.yaml").read_text())}
    blind = {case: terms for case, terms in blind.items() if case not in ABOUT_THE_GUIDANCE_TOPIC}
    terms = SMOKE_TERMS + [t.lower() for case_terms in blind.values() for t in case_terms
                           if hashlib.sha256(t.lower().encode()).hexdigest() not in GENERIC_OVERLAP_SHA256]
    hits = [f.name for f in SKILLS_DIR.rglob("*.md") for t in terms if t in f.read_text().lower()]
    assert not hits, f"case-specific terms found in: {sorted(set(hits))} (terms hidden to preserve blinding)"


@pytest.mark.skipif(not freeze.RECORD.exists(), reason="not frozen yet")
def test_cases_unchanged_since_the_freeze():
    assert freeze.differences() == [], "eval cases changed after the freeze: document the defect in PREREGISTRATION.md"


def test_coverage_map_points_at_real_scenarios_sections_and_references():
    text = (EVALS.parent / "docs" / "coverage-map.md").read_text()
    known = {scenario["id"] for scenario in SCENARIOS}
    cited = set(re.findall(r"\bs\d\d\b", text))
    assert cited and cited <= known, cited - known
    assert known <= cited, f"scenarios with no control mapped: {sorted(known - cited)}"
    if SKILL_DIR.exists():
        skill = (SKILL_DIR / "SKILL.md").read_text()
        rows = [line.split("|")[8].strip() for line in text.splitlines() if line.count("|") >= 10][2:]
        places = {part.strip() for row in rows for part in row.split(";")}
        headings = {line[3:].strip() for line in skill.splitlines() if line.startswith("## ")}
        references = {path.stem for path in (SKILL_DIR / "references").glob("*.md")}
        languages = {path.parent.name for path in SKILLS_DIR.glob("occam-*/SKILL.md")} | {"language skills"}
        allowed = headings | references | languages | {"adapters", "plugin", "Whole package"}
        assert places <= allowed, f"not real sections: {sorted(places - allowed)}"
