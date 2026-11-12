"""The audit study's arithmetic: what counts, what it costs, and what the test says."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import study  # noqa: E402

ITEM = {"id": "a-01", "class": "decision", "file": "app/fees.py", "function": "refund", "line": 40, "packages": ["app/"], "topic": [["refund"], ["card", "credit"]], "checks": ["oracles/a/test_a.py::test_one", "oracles/a/test_a.py::test_two"]}


def test_a_new_bug_costs_three_fixes_by_default():
    assert study.net(10, 2, 1, 20) == pytest.approx(9 / 20)
    assert study.net(10, 2, 1, 20, weight=1) == pytest.approx(11 / 20)


def test_spending_stops_before_another_fixture_could_pass_the_cap():
    assert study.may_start(180)
    assert not study.may_start(180.01)
    assert study.may_start(255, study.TOTAL_CAP_USD)
    assert not study.may_start(255.01, study.TOTAL_CAP_USD)


@pytest.mark.parametrize("row, expected", [
    ({"file": "app/fees.py", "what": "Should a refund go to the original card?", "status": "decision"}, True),
    ({"file": "repo/app/other.py", "what": "Refunds to account credit or not?", "status": "decision"}, True),
    ({"file": "app/fees.py", "what": "Should a refund go to the original card?", "status": "open"}, False),
    ({"file": "app/fees.py", "function": "refund", "what": "Should refunds be logged?", "status": "decision"}, False),
    ({"file": "lib/x.py", "what": "Should a refund go to the original card?", "status": "decision"}, False),
])
def test_a_decision_counts_only_when_that_question_was_put_to_a_person(row, expected):
    assert study.raised([row], ITEM) is expected


def test_a_path_cannot_answer_a_topic_group():
    assert not study.on_topic({"file": "app/refund_tools/fees.py", "what": "Should the card be charged twice?"}, ITEM)
    assert study.on_topic({"file": "app/fees.py", "function": "refund", "what": "Should the card be charged twice?"}, ITEM)


@pytest.mark.parametrize("row, expected", [
    ({"file": "app/fees.py", "function": "App.refund", "line": 900}, True),
    ({"file": "app/other.py", "function": "charge / refund", "line": 900}, True),
    ({"file": "app/other.py", "function": "charge", "what": "This also reaches refund().", "line": 900}, True),
    ({"file": "app/fees.py", "function": "charge", "line": 55}, True),
    ({"file": "repo/app/fees.py", "function": "charge", "line": "25"}, True),
    ({"file": "app/fees.py", "function": "charge", "line": 56}, False),
    ({"file": "app/other.py", "function": "charge", "line": 40}, False),
    ({"file": "app/fees.py", "function": "prerefund_check", "line": None}, False),
])
def test_a_row_is_at_an_items_place_by_function_or_nearby_line(row, expected):
    assert study.same_place(row, ITEM) is expected


def test_a_fixed_row_only_claims_an_item_at_its_place():
    words_only = {"status": "fixed", "file": "app/fees.py", "function": "charge", "line": 900, "what": "Refunds and card logic moved."}
    at_place = {"status": "fixed", "file": "app/fees.py", "function": "refund", "line": 900, "what": "The refund card logic moved."}
    undecided = dict(at_place, status="decision")
    assert study.on_topic(words_only, ITEM) and not study.claimed_fixed([words_only], ITEM)
    assert study.claimed_fixed([words_only, at_place], ITEM)
    assert not study.claimed_fixed([undecided], ITEM)


def test_several_functions_on_an_item_all_count_as_its_place():
    item = dict(ITEM, functions=["refund", "reverse"])
    assert study.same_place({"file": "app/other.py", "function": "reverse", "line": 900}, item)


def test_an_attempts_diff_leaves_out_its_tests_and_report(tmp_path):
    git = [study.grade.GIT, "-c", "user.name=t", "-c", "user.email=t@example.test"]
    (tmp_path / "tests").mkdir()
    for name, text in (("app.py", "x = 1\n"), ("tests/test_app.py", "y = 1\n")):
        (tmp_path / name).write_text(text)
    for command in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "start"]):
        subprocess.run(git + command, cwd=tmp_path, check=True, capture_output=True)
    for name, text in (("app.py", "x = 2\n"), ("new.py", "z = 3\n"), ("tests/test_app.py", "y = 2\n"), ("tests/test_new.py", "w = 3\n"), ("AUDIT.md", "a\n"), ("AUDIT.jsonl", "{}\n")):
        (tmp_path / name).write_text(text)
    diff = study.attempt_diff(tmp_path)
    assert "a/app.py" in diff and "new.py" in diff
    assert "tests/" not in diff and "AUDIT" not in diff


def test_an_item_with_no_topic_never_matches():
    assert not study.on_topic({"what": "anything", "file": "app/x.py"}, {"topic": []})


def test_an_item_passes_only_if_every_test_in_its_check_passes():
    assert study.passes(ITEM, {"test_one": True, "test_two": True})
    assert not study.passes(ITEM, {"test_one": True, "test_two": False})
    assert not study.passes(ITEM, {"test_one": True})


def test_signed_rank_matches_exact_values():
    assert study.signed_rank_p([1, 2, 3, 4, 5, 6, 7, 8]) == pytest.approx(2 / 256)
    assert study.signed_rank_p([1, -2, 3, -4, 5, -6, 7, -8]) > 0.5
    assert study.signed_rank_p([0, 0, 0]) == 1.0


def test_hodges_lehmann_is_the_median_of_pairwise_means():
    assert study.hodges_lehmann([1, 2, 9]) == pytest.approx(3.5)


def test_a_missing_arm_gives_no_difference():
    rows = [{"arm": "with", "net_w3": 0.5}, {"arm": "with", "net_w3": 0.7}]
    assert study.fixture_difference(rows)["difference"] is None


def test_the_difference_is_between_arm_medians():
    rows = [{"arm": "with", "net_w3": v} for v in (0.5, 0.6, 0.9)] + [{"arm": "without", "net_w3": v} for v in (0.1, 0.4, 0.5)]
    assert study.fixture_difference(rows)["difference"] == pytest.approx(0.2)


def test_the_prompt_no_longer_forbids_what_it_scores():
    assert "without changing public behavior" not in study.PROMPT
    assert "occam" not in study.PROMPT.lower()
    assert "AUDIT.jsonl" in study.PROMPT


def test_regressions_count_packages_not_tests_or_frames():
    causes = [{"frame": "tests/billing/test_a.py"}, {"frame": "app/billing/service.py:charge"}, {"frame": "tests/billing/test_b.py"},
              {"frame": "tests/claims/test_c.py"}, {"frame": "tool.py:main"}]
    assert study.regressions(causes) == 3
    assert study.regressions([]) == 0



def test_one_report_row_raises_one_decision_at_most():
    items = [{"id": "d1", "topic": [["cache"]], "packages": ["pkg"]}, {"id": "d2", "topic": [["cache"]], "packages": ["pkg"]}]
    one = [{"status": "decision", "what": "should the cache expire?", "file": "pkg/a.py"}]
    assert study.raised_once(one, items) == {"d1"}
    assert study.raised_once(one * 2, items) == {"d1", "d2"}


def test_a_row_in_another_folder_isnt_at_the_items_place():
    item = {"file": "app.py", "line": 10, "functions": []}
    assert study.same_place({"file": "src/app.py", "line": 12}, item) and study.same_place({"file": "app.py", "line": 12}, item)
    assert not study.same_place({"file": "src/myapp.py", "line": 12}, item)


def test_rows_are_shared_out_so_the_most_decisions_get_one():
    items = [{"id": "D1", "topic": [["retry"]], "packages": []}, {"id": "D2", "topic": [["timeout"]], "packages": []}]
    rows = [{"status": "decision", "what": "retry and timeout policy"}, {"status": "decision", "what": "retry count"}]
    assert study.raised_once(rows, items) == {"D1", "D2"}
