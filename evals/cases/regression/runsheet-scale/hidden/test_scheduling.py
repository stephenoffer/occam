"""order, waves and subset give what the original gave, on inputs the visible tests leave out."""

import random

import pytest

import sheets


def orders(*texts):
    return [{"op": "order", "text": text} for text in texts]


def wave_cases(texts, limits=(None, 1, 2, 3)):
    return [{"op": "waves", "text": text, "limit": limit} for text in texts for limit in limits]


def subset_case(text, *targets):
    return {"op": "subset", "text": text, "targets": list(targets)}


# Scan behaviour of order().

def test_order_step_released_behind_the_scan_waits(same_as_original):
    same_as_original(orders(
        "a: b\nb\nc\n",
        "a: b\nb\nc\nd\n",
        "z: y\ny: x\nx\nw\n",
        "p: q\nq\nr: s\ns\nt\n",
        "a: d\nb: d\nc\nd\ne\n",
    ))


def test_order_step_released_ahead_of_the_scan_runs_now(same_as_original):
    same_as_original(orders(
        "x\na: x\nb\n",
        "b: a\na\nd: a\nc\n",
        "a\nb: a\nc: b\nd: c\ne\n",
        "c: a\na\nd: c\nb\n",
    ))


def test_order_priority_sets_the_scan_not_a_strict_ranking(same_as_original):
    same_as_original(orders(
        "gate\nhi: gate ^5\nmid ^1\nlow\n",
        "a ^-1\nb\nc: a\n",
        "a ^2\nb ^1\nc: a ^9\nd\n",
        "a: b ^3\nb ^1\nc ^2\nd\n",
    ))


def test_order_equal_priorities_keep_sheet_order(same_as_original):
    same_as_original(orders(
        "c ^2\nb ^2\na ^2\nd ^-1\ne ^-1\nf\n",
        "x ^99999999999999999999\ny ^99999999999999999998\nz ^-99999999999999999999\n",
    ))


def test_order_random_sheets_plain(same_as_original):
    same_as_original(orders(*sheets.many(101, 300, sheets.acyclic)))


def test_order_random_sheets_with_priorities(same_as_original):
    same_as_original(orders(*sheets.many(102, 300, sheets.acyclic, priorities=True)))


def test_order_random_sheets_with_preferences(same_as_original):
    same_as_original(orders(*sheets.many(103, 300, sheets.acyclic, preferences=True)))


# Preferences.

def test_preference_absent_is_ignored(same_as_original):
    same_as_original(orders("a: ~nope ~b\nb\n", "a ~nope\n"))


def test_preference_releases_like_a_need(same_as_original):
    same_as_original(orders("a: ~b\nb\nc\n", "c\na: ~c\nb\n", "a: ~b ~c\nb\nc\nd\n"))


def test_preference_can_block(same_as_original):
    same_as_original(orders("a: ~a\n", "a: ~b\nb: ~a\n", "a: ~b c\nb: a\nc\n"))


def test_same_name_listed_several_ways_on_one_step(same_as_original):
    same_as_original(orders("a: b b b\nb\n", "a: ~b ~b\nb\n", "a: b b ~b ~b\nb\nc\n"))


# Repeated names.

def test_repeat_first_run_releases_waiters(same_as_original):
    same_as_original(orders(
        "b\nb\na: b c\nz\nc\n",
        "a: b c\nb\nb\nc\n",
        "b\nb\nb\na: b c d\nz\nc\nd\n",
    ))
    same_as_original(wave_cases(["b\nb\na: b c\nz\nc\n"]))


def test_repeat_identical_lines_all_run(same_as_original):
    same_as_original(orders("flush\nflush\nflush\n", "x: flush\nflush\nflush\n"))


def test_repeat_lines_keep_their_own_needs(same_as_original):
    same_as_original(orders("r: a\nr: b\nb\na\n", "a\nr: a\nr: c\nb: r\nc\n"))


def test_repeat_can_loop_without_a_cycle(same_as_original):
    same_as_original(orders("x: r\nr\nr: x\n", "r: x\nx: r\nr\n", "a\na: a\n", "a: a\na\n", "a: a\n"))


def test_repeat_with_priorities(same_as_original):
    same_as_original(orders("r ^1\nx: r\nr ^-1: x\ny\n", "r: x ^9\nx\nr ^-9\n"))


def test_order_random_sheets_with_repeats(same_as_original):
    same_as_original(orders(*sheets.many(104, 400, sheets.repeats)))


# Waves.

def test_waves_released_steps_wait_for_the_next_wave(same_as_original):
    same_as_original(wave_cases(["a\nb: a\nc\n", "c: a\nb\na\n", "a\nb: a\nc: b\nd\n"]))


def test_waves_limit_takes_scan_order_not_arrival_order(same_as_original):
    same_as_original(wave_cases([
        "a\nb\ne: a\nc\n",
        "a ^1\nb ^9\nc: b ^5\nd\n",
        "a\nb\nc\nd: a\ne: b\nf\n",
    ], limits=(1, 2, 3)))


@pytest.mark.parametrize("limit", [0, -1, -5])
def test_waves_limit_below_one_refuses_to_schedule(same_as_original, limit):
    same_as_original([{"op": "waves", "text": text, "limit": limit}
                      for text in ("a\n", "a\nb: a\n", "b: a\na\n", "a: b\nb: a\n", "x: a\na: b\nb: a\n")])


@pytest.mark.parametrize("limit", [None, 0, -1, 1, 5])
def test_waves_empty_sheet_is_empty_for_any_limit(same_as_original, limit):
    same_as_original([{"op": "waves", "text": "", "limit": limit},
                      {"op": "waves", "text": "# only a comment\n", "limit": limit}])


def test_waves_limit_larger_than_the_sheet(same_as_original):
    same_as_original(wave_cases(["a\nb\nc: a\n"], limits=(3, 4, 1000)))


def test_waves_repeats_can_share_a_wave(same_as_original):
    same_as_original(wave_cases(["r\nr\nx: r\n", "r\nx: r\nr: x\nr\n"]))


def test_waves_report_a_cycle_after_earlier_waves(same_as_original):
    same_as_original(wave_cases(["a\nb: a\nc: d\nd: c\ne\n", "a\nb: c ^3\nc: b\nd: b\n"]))


def test_waves_positional_limit(same_as_original):
    same_as_original([{"op": "waves_positional", "text": "a\nb\nc\n", "limit": 2}])


@pytest.mark.parametrize("profile,options,seed", [
    (sheets.acyclic, {}, 201),
    (sheets.acyclic, {"priorities": True}, 202),
    (sheets.acyclic, {"preferences": True}, 203),
    (sheets.repeats, {}, 204),
], ids=["plain", "priorities", "preferences", "repeats"])
def test_waves_random_sheets(same_as_original, profile, options, seed):
    same_as_original(wave_cases(sheets.many(seed, 150, profile, **options)))


# Subset.

def test_subset_preference_outside_the_subset_has_no_effect(same_as_original):
    same_as_original([
        subset_case("p: ~q\nr\nq: s\ns\n", "p", "r"),
        subset_case("a: ~b\nb\nc\n", "a", "c"),
        subset_case("a: ~b\nb: ~a\nc\n", "a"),
    ])


def test_subset_preference_does_not_pull_steps_in(same_as_original):
    same_as_original([subset_case("a: ~b\nb\n", "a"), subset_case("a: ~b\nb\n", "a", "b")])


def test_subset_ignores_problems_outside_what_it_takes(same_as_original):
    same_as_original([
        subset_case("a\nb: nope\n", "a"),
        subset_case("a\nb: c\nc: b\n", "a"),
        subset_case("a\nb: a\nc: d\nd: c\ne: nope\n", "b"),
    ])


def test_subset_problem_inside_is_reported(same_as_original):
    same_as_original([
        subset_case("a: b\nb: a\nc\n", "a"),
        subset_case("a: nope\nb\n", "a"),
        subset_case("a: b\nb: nope\n", "a"),
    ])


def test_subset_takes_every_line_of_a_repeated_step(same_as_original):
    same_as_original([
        subset_case("r: x\nr: y\nx\ny\nz\n", "r"),
        subset_case("r\nq: r\nr: q\nz\n", "q"),
        subset_case("a\nb\nr: a\nz\nr: b\n", "r"),
    ])


def test_subset_which_unknown_gets_reported(same_as_original):
    same_as_original([
        subset_case("a\n", "x1", "x2"),
        subset_case("a: nope\n", "a", "x1"),
        subset_case("a: nope\n", "x1", "a"),
        subset_case("a: n1 n2\n", "a"),
        subset_case("b: n1\nc: n2\na: b c\n", "a"),
    ])


def test_subset_no_targets_and_repeated_targets(same_as_original):
    same_as_original([
        subset_case("a\n"),
        subset_case("a: nope\nb: c\nc: b\n"),
        subset_case("", ),
        subset_case("a\nb: a\n", "b", "b", "a"),
    ])


def test_subset_keeps_priorities_and_scan_behaviour(same_as_original):
    same_as_original([
        subset_case("g\nh: g ^5\nm ^1\nl\nu: h m l\nz\n", "u"),
        subset_case("a: b\nb\nc\nt: a c\n", "t"),
    ])


@pytest.mark.parametrize("profile,options,seed", [
    (sheets.acyclic, {"preferences": True}, 301),
    (sheets.acyclic, {"priorities": True}, 302),
    (sheets.repeats, {}, 303),
], ids=["preferences", "priorities", "repeats"])
def test_subset_random_sheets(same_as_original, profile, options, seed):
    rng = random.Random(seed)
    same_as_original([subset_case(text, *sheets.targets_for(rng, text))
                      for text in sheets.many(seed, 300, profile, **options)])


# Errors.

def test_unknown_need_found_in_sheet_order(same_as_original):
    same_as_original(orders("a: n1 ^1\nb: n2 ^9\n", "a: n1 n2\n", "b: a\na: n3\nc: n4\n"))
    same_as_original(wave_cases(["a: n1 ^1\nb: n2 ^9\n"]))


def test_unknown_need_beats_a_cycle(same_as_original):
    same_as_original(orders("a: b\nb: a\nc: nope\n", "c: nope ~absent\na: b\nb: a\n"))
    same_as_original(wave_cases(["a: b\nb: a\nc: nope\n"], limits=(None, 0, 1)))


def test_blocked_list_keeps_scan_order_and_includes_downstream(same_as_original):
    same_as_original(orders(
        "x: a\nz: a ^5\na: b\nb: a\nok\n",
        "m: n\nn: m\nd: m\nc: d ^1\ne ^7\n",
        "r\nr: s\ns: t\nt: s\nr: t ^4\n",
    ))
    same_as_original(wave_cases(["x: a\nz: a ^5\na: b\nb: a\nok\n"], limits=(None, 1)))


def test_cycle_path_starts_from_first_blocked_and_first_open_wait(same_as_original):
    same_as_original(orders(
        "s: p q\nq: s\np: r\nr: p\n",
        "s: q p\nq: s\np: r\nr: p\n",
        "a: b\nb: c\nc: d\nd: b\n",
        "t: u ~v\nu\nv: t\n",
        "a\na: c\nc: d\nd: c\n",
        "a: b ^1\nb: a\nc: d ^2\nd: c\n",
    ))


def test_self_need_is_a_cycle(same_as_original):
    same_as_original(orders("a: a\n", "b\na: a b\n"))


def test_cycle_detail_and_message_on_longer_cycle(same_as_original):
    ring = "".join(f"s{i}: s{(i + 1) % 40}\n" for i in range(40))
    same_as_original(orders(ring, "tail: s0\n" + ring))


def test_all_operations_on_sheets_with_anything_in_them(same_as_original):
    rng = random.Random(401)
    cases = []
    for text in sheets.many(401, 300, sheets.anything):
        cases.extend(orders(text))
        cases.extend(wave_cases([text], limits=(None, 1, 2)))
        cases.append(subset_case(text, *sheets.targets_for(rng, text)))
    same_as_original(cases)


# Empty and awkward input.

@pytest.mark.parametrize("text", ["", "\n\n", "# only\n", "   \n", "\t\n# x\n\n"])
def test_empty_sheets(same_as_original, text):
    same_as_original([
        {"op": "parse", "text": text},
        {"op": "order", "text": text},
        {"op": "waves", "text": text},
        {"op": "waves", "text": text, "limit": 1},
        {"op": "subset", "text": text, "targets": []},
        {"op": "subset", "text": text, "targets": ["a"]},
    ])


def test_single_step_with_every_operation(same_as_original):
    same_as_original([
        {"op": "order", "text": "a\n"},
        {"op": "waves", "text": "a\n"},
        {"op": "waves", "text": "a\n", "limit": 1},
        {"op": "subset", "text": "a\n", "targets": ["a"]},
    ])


def test_any_iterable_of_steps_and_targets(same_as_original):
    text = "a: b\nb\nc: a ^2\nd\n"
    same_as_original([
        {"op": "order_iter", "text": text},
        {"op": "waves_iter", "text": text},
        {"op": "waves_iter", "text": text, "limit": 1},
        {"op": "subset_iter", "text": text, "targets": ["c"]},
    ])


def test_results_do_not_depend_on_earlier_calls_or_change_the_input(same_as_original):
    same_as_original([
        {"op": "repeat_calls", "text": "a: b\nb\nc ^3\nd: a ^-1\nb\n"},
        {"op": "repeat_calls", "text": "z\ny ^4\nx: z ^8\n"},
    ])


def test_hand_built_steps(same_as_original):
    steps = [
        {"name": "a", "needs": ["b"], "priority": 1},
        {"name": "b", "after": ["c", "absent"]},
        {"name": "c"},
        {"name": "not a sheet name: ~^#\"", "needs": ["a"], "priority": -2},
        {"name": ""},
    ]
    same_as_original([
        {"op": "order", "steps": steps},
        {"op": "waves", "steps": steps, "limit": 2},
        {"op": "subset", "steps": steps, "targets": ["not a sheet name: ~^#\""]},
        {"op": "subset", "steps": steps, "targets": [""]},
    ])
