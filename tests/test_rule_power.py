"""A round's verdict is only as good as its rule, so the rule's error rates are computed and pinned."""

import rule_power


def test_margins_match_the_table_fixed_in_the_preregistration():
    assert [rule_power.margin_for(cases) for cases in range(4, 9)] == [5, 5, 5, 6, 6]


def test_a_margin_of_three_on_eight_cases_would_win_too_often():
    false_win = max(rule_power.at_least(rule_power.round_gain(spread, 0.0, 8, 3), 3) for spread in rule_power.SPREADS.values())
    assert false_win > 0.10


def test_no_effect_is_symmetric_and_a_real_lift_moves_the_total_up():
    spread = rule_power.SPREADS["mixed"]
    null = rule_power.round_gain(spread, 0.0, 4, 3)
    assert abs(sum(null.values()) - 1) < 1e-9
    assert abs(rule_power.at_least(null, 5) - rule_power.at_least({-k: v for k, v in null.items()}, 5)) < 1e-9
    assert rule_power.at_least(rule_power.round_gain(spread, 0.3, 4, 3), 5) > rule_power.at_least(null, 5)
