#!/usr/bin/env python3
"""How often a round's decision rule is wrong, by exact calculation. Spends nothing.

    rule_power.py [--runs 3]

The rule: total gain across kept cases of at least the margin reads as helping, and the same margin the other way as
harm. A case is kept if at least one of two no-skill pilot runs fails, so each assumed spread of no-skill pass rates is
weighted for that. The margin is the smallest whose false win stays at or under 5% for every spread.

This assumes the same lift on every case, and independent runs. Neither is fully true, so the margins are calibrated
rather than exact, and the power columns are a guide.
"""

import argparse
from math import comb

# Assumed spreads of a kept case's true no-skill pass rate, as {pass rate: weight before selection}.
SPREADS = {
    "mixed": {0.0: 1, 0.2: 1, 0.4: 1, 0.6: 1, 0.8: 1, 1.0: 1},
    "mostly high": {0.2: 1, 0.5: 2, 0.7: 3, 0.9: 3},
    "mostly low": {0.0: 3, 0.1: 3, 0.3: 2, 0.6: 1},
}
FALSE_WIN_LIMIT = 0.05


def binomial(runs, rate):
    return [comb(runs, k) * rate**k * (1 - rate) ** (runs - k) for k in range(runs + 1)]


def convolve(first, second):
    total = {}
    for a, x in first.items():
        for b, y in second.items():
            total[a + b] = total.get(a + b, 0) + x * y
    return total


def case_gain(spread, lift, runs):
    """Distribution of plugin passes minus no-skill passes on one kept case."""
    weights = {rate: weight * (1 - rate * rate) for rate, weight in spread.items()}
    total = sum(weights.values())
    gain = {}
    for rate, weight in weights.items():
        plugin = binomial(runs, min(0.98, max(0.0, rate + lift)))
        for i, x in enumerate(binomial(runs, rate)):
            for j, y in enumerate(plugin):
                gain[j - i] = gain.get(j - i, 0) + x * y * weight / total
    return gain


def round_gain(spread, lift, cases, runs):
    one = case_gain(spread, lift, runs)
    gain = {0: 1.0}
    for _ in range(cases):
        gain = convolve(gain, one)
    return gain


def at_least(gain, margin):
    return sum(chance for value, chance in gain.items() if value >= margin)


def margin_for(cases, runs=3):
    """Smallest total gain with a false win of at most 5% under every spread."""
    for margin in range(1, cases * runs + 1):
        if all(at_least(round_gain(spread, 0.0, cases, runs), margin) <= FALSE_WIN_LIMIT for spread in SPREADS.values()):
            return margin
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    print("| Kept cases | Margin | Worst false win | Power at +.15 | Power at +.30 |\n|---:|---:|---:|---|---|")
    for cases in range(4, 9):
        margin = margin_for(cases, args.runs)
        false_win = max(at_least(round_gain(s, 0.0, cases, args.runs), margin) for s in SPREADS.values())
        power = [[at_least(round_gain(s, lift, cases, args.runs), margin) for s in SPREADS.values()] for lift in (0.15, 0.30)]
        print(f"| {cases} | {margin} | {false_win:.1%} | " + " | ".join(f"{min(p):.0%} to {max(p):.0%}" for p in power) + " |")


if __name__ == "__main__":
    main()
