import pytest

from runsheet import CycleError, UnknownStepError, order, parse, subset, waves


def test_sheet_already_in_order_stays_in_order():
    steps = parse("a\nb: a\nx\nc: b\n")
    assert order(steps) == ["a", "b", "x", "c"]


def test_needs_listed_later_in_the_sheet():
    steps = parse("c: b\nb: a\na\n")
    assert order(steps) == ["a", "b", "c"]


def test_diamond():
    steps = parse("a\nb: a\nc: a\nd: b c\n")
    assert order(steps) == ["a", "b", "c", "d"]


def test_priority_breaks_ties():
    steps = parse("a\nb ^5\nc\n")
    assert order(steps) == ["b", "a", "c"]


def test_preference_applies_when_present():
    assert order(parse("web: ~warm\nwarm\n")) == ["warm", "web"]


def test_preference_ignored_when_absent():
    assert order(parse("web: ~warm\n")) == ["web"]


def test_repeated_step_runs_each_time():
    steps = parse("flush\nmigrate: flush\nflush: migrate\n")
    assert order(steps) == ["flush", "migrate", "flush"]


def test_unknown_need():
    with pytest.raises(UnknownStepError) as caught:
        order(parse("web: nope\n"))
    assert caught.value.missing == "nope"
    assert caught.value.needed_by == "web"


def test_cycle():
    with pytest.raises(CycleError) as caught:
        order(parse("a: b\nb: a\n"))
    assert sorted(caught.value.blocked) == ["a", "b"]


def test_waves_of_a_diamond():
    steps = parse("a\nb: a\nc: a\nd: b c\n")
    assert waves(steps) == [["a"], ["b", "c"], ["d"]]


def test_waves_with_limit():
    assert waves(parse("a\nb\nc\n"), limit=2) == [["a", "b"], ["c"]]


def test_subset_takes_what_targets_need():
    steps = parse("a\nb: a\nc\nd: b\n")
    assert subset(steps, ["b"]) == ["a", "b"]


def test_subset_unknown_target():
    with pytest.raises(UnknownStepError):
        subset(parse("a\n"), ["nope"])
