"""The scenario spec is complete, honest about status, and the cases have not moved since the freeze."""

import hashlib
import re
import shutil
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


def leak_terms(suite: str) -> dict:
    """A suite in the middle of a blind round is kept out of the published repository until its runs are done, so it may not be here."""
    path = EVALS / "cases" / suite / "LEAK_TERMS.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def test_blind_prompts_do_not_leak_their_diagnosis():
    for suite in ("holdout", "regression", "python", "hard"):
        terms = leak_terms(suite)
        # A prompt has to be able to name its own entry point, so a term that is part of the case's name is fine.
        leaks = {case: [t for t in case_terms if t.lower() in prompt_body(EVALS / "cases" / suite / case) and t.lower() not in case]
                 for case, case_terms in terms.items()}
        assert not any(leaks.values()), f"a {suite} prompt contains its diagnosis terms (names hidden to preserve blinding)"


# Identifiers and phrases specific to smoke fixtures. The skill must teach general judgment, not these answers.
SMOKE_TERMS = ["to_url_token", "round_invoice_total", "round_display_amount", "get_invoices", "nextpagetoken",
               "vendor_sandbox", "fake_vendor", "logmerge", "ledgerkit", "bulkfetch", "crmsync", "stockreport",
               "enrich_record", "loyalty", "review-checkin", "reviewer-metrics", "requiresignature", "access_log"]


# Holdout list entries a blinded adjudicator judged to be generic vocabulary, by hash so the skill author stays blind.
GENERIC_OVERLAP_SHA256 = {
    "051af376199dec216b4807623fae755a2c013911d8219aa607787b17e3ed9cd7",
    "19d6f9338c227b9d04bfdff178cdf3eddf36aae0a75ba148cb1cf0577cb90201",
    "21f74b3077447b5013ee944feeb5f1c063b24981c52b48824d52943fd18e7c5b",
    "24abad971443cc52ab099910bb9ca6b3a19f1f8ff8cda24715f51af82d184e75",
    "261de6d9264f3a025e8d5a2fed7be0176f17c966f73fd979f99ff506e9dbde07",
    "274f2e9a4b40fb846cba14b3ed16cf9eed4822b124add2c907c05769848b26ba",
    "363f96d787513cbefdce00668dacfe0844689af0d560fb84b741498752a30788",
    "3c33767f9e3bc905562cbfed71e115fd1e1dd2ca65ed626a0dd1781f6aa5e4d2",
    "3e6d4b43d473c69d919c7550b0468718a2e66daf934e0428b401e230c5d34d85",
    "4027f515418b77482d033970fe4e6cc2c9b6dbd8d19201c31afd06d080a07f41",
    "46a9c200972d180c2b6fb7a30307210162070e1f5ec08b84879412dc053bc3e7",
    "46ede93b09bfe7da5d11716d8e00be347779c5e12c8ae9a93d533ecf9b248180",
    "471233bcc8c3a54aa229efc6159bcd91480628b6025b099451688a57988c0803",
    "76a7e234dc54e9c605b2cc9fdf71279526150df48c574bdfa69e436e0b3d5c18",
    "a03f2386ae06b21109577020844df367857b72c2fcce384c1896fed98a89c82b",
    "af76eb7f9a5683f436ad133dd307447a942cf06dcc9dadb3b70307dc5bf7355e",
    "bd8a39e42ac8ff9bc08b4b4ece077f10657644186a1946222e4ddab6f1e4be01",
    "c1d60fe5815fb5b2d8eadc7c686a2ef228818eb63d14a58be0336c2d4dc3bb65",
    "ce922519a3c3ecaf9b0986c2449c7680895c15f4b0e9818e994e14a4d28b6aaf",
    "da25480fb483e6ce3d30f1a179c3c07e9f3b045425b0ac54acc6758a97e2db62",
    "da47c2f450a4f9d538d86d600d55149afd39d6672fdd1f30c68ad5be21cadad8",
    "db8cf3338c29849e56bf0b0c9aa8eeaa1a87d168f31979fd533e2ad9cd45a103",
    "e484eeb74a6fcc28e739cc8629bcb7475f9a465df8b420228ea14efb67027723",
    "e5c95ce553962409041e188001bea4783a5f098c6612e854fd825f41534011aa",
    "eed2036cbe1ffd83e4646ee815d6222389feb2056d7b9c385157860f8c3b2ce9",
    "eed6ffb747c1e987329be5f3b73ada98f116c48d21933102ce9782586ff1a56f",
    "fd43322a4da6f0e914c9624d6248d376a1518a9964349ed64679d316d7af8290",
}
# s47 tests the same APIs and sinks the guidance names, so this case's list overlaps it by design: a blinded adjudicator found
# 23 of 41 terms in the guidance, all generic. A case-level exception keeps the exemption above from weakening other cases.
ABOUT_THE_GUIDANCE_TOPIC = {"partner-meter-backfill"}
# Their diagnoses are stated in the guidance as general advice. Not a leak, since neither side saw the other, but a win on
# these cases can't be credited to general judgment, and PREREGISTRATION.md reports them apart.
STATED_AS_GENERAL_GUIDANCE_SHA256 = {
    "106544cd14d18ab035030bb18047f438ed46137ee94b735088203645426db866",
    "206fdcfc18ef062a51e30eebc2122ec4656dfa2c2f2d1107264ed23df39c7c01",
    "2cf2fb7f867feffafbfe66a5b8e8822da70738406dd3b85a28c83892da6e50a5",
    "2ee32f5ece03681d50a2cf0ad37c6e65a08cb45ac4fe434bc072533bd91b643b",
    "3962edee9c25c9b904d84a4f438bc889c566f6a3d0e01f406cf387f1f41576ea",
    "4248cbb23dab1430d10ce618b98b682b26dc1f6d4978a1891bceea7dc3709c53",
    "44b2d89ca748e2c1300918f5490302467300754b5ea4e21e61c250ac080175bb",
    "6d08a4e630e4aa0d5cd873e65aea0a23df42de61073ecb49ef17158fe6a9dcea",
    "7772189a259534b293ca813cb5bdb069828abb2a15fd7f8e0aab0face30cda22",
    "7c40dc7dfb0d02b59c857553bd7b9c1a1a25be1b2e187b08a11b83d3ee89991f",
    "81d1c939a5a05e28c9ef3085efe264636b3e75d9533e3d9faf33507a9d6fe892",
    "8297e58c62f0d4a6ae4bf506d53c7b25520ee9a168ce01ebe1600580ffd1719c",
    "d049a4c844b96ae77a9ba0352c98ab4eed1eb7718a370509943b257fd0d138fc",
    "d6b67e006108e6816d84d92fd9035ad1c8cf72bab11d828d0a344f9927d52103",
    "e8779f5293c0dbd38118daa3b3fdcaab08108617439432d0c7ce49158c592735",
    "f5d39a07e87f63da289b4c3ff8d5adfc6d1e493ad381b2bb24260dc032f1de06",
}


@pytest.mark.skipif(not SKILL_DIR.exists(), reason="skill not written yet")
def test_skill_contains_no_case_specific_terms():
    blind = {**yaml.safe_load((EVALS / "cases" / "holdout" / "LEAK_TERMS.yaml").read_text()),
             **yaml.safe_load((EVALS / "cases" / "regression" / "LEAK_TERMS.yaml").read_text()),
             **yaml.safe_load((EVALS / "cases" / "python" / "LEAK_TERMS.yaml").read_text()),
             **leak_terms("hard")}
    blind = {case: terms for case, terms in blind.items() if case not in ABOUT_THE_GUIDANCE_TOPIC}
    exempt = GENERIC_OVERLAP_SHA256 | STATED_AS_GENERAL_GUIDANCE_SHA256
    terms = SMOKE_TERMS + [t.lower() for case_terms in blind.values() for t in case_terms
                           if hashlib.sha256(t.lower().encode()).hexdigest() not in exempt]
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


def freeze_in(tmp_path, monkeypatch, *names):
    monkeypatch.setattr(freeze, "EVALS", tmp_path)
    monkeypatch.setattr(freeze, "RECORD", tmp_path / "FROZEN.sha256")
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    freeze.RECORD.write_text("".join(f"{digest}  {name}\n" for name, digest in freeze.current().items()))


def test_a_suite_withheld_during_a_blind_round_doesnt_read_as_changed(tmp_path, monkeypatch):
    freeze_in(tmp_path, monkeypatch, "cases/hard/a/prompt.md", "cases/python/b/prompt.md")
    shutil.rmtree(tmp_path / "cases" / "hard")
    assert freeze.differences() == []


def test_any_other_missing_suite_or_a_changed_file_in_a_withheld_one_still_shows(tmp_path, monkeypatch):
    freeze_in(tmp_path, monkeypatch, "cases/hard/a/prompt.md", "cases/python/b/prompt.md")
    (tmp_path / "cases" / "hard" / "a" / "prompt.md").write_text("changed")
    shutil.rmtree(tmp_path / "cases" / "python")
    assert freeze.differences() == ["cases/hard/a/prompt.md", "cases/python/b/prompt.md"]

