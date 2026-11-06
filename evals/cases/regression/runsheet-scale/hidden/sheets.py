"""Seeded random run sheets for comparing against the original."""

import random


def _line(name, needs=(), after=(), priority=None):
    parts = [name, ":"] + list(needs) + [f"~{a}" for a in after]
    if priority is not None:
        parts.append(f"^{priority}")
    return " ".join(parts)


def acyclic(rng, priorities=False, preferences=False):
    size = rng.randint(1, 30)
    lines = []
    for index in range(size):
        earlier = range(index)
        needs = [f"s{i}" for i in rng.sample(earlier, min(index, rng.choice((0, 1, 1, 2, 3))))]
        after = []
        if preferences:
            after = [f"s{i}" for i in rng.sample(earlier, min(index, rng.choice((0, 0, 1))))]
            after += ["absent"] * rng.choice((0, 0, 1))
        priority = rng.choice((-1, 0, 0, 0, 1, 2)) if priorities else None
        lines.append(_line(f"s{index}", needs, after, priority))
    rng.shuffle(lines)
    return "\n".join(lines) + "\n"


def repeats(rng):
    pool = [f"r{i}" for i in range(rng.randint(2, 8))]
    lines = []
    for _ in range(rng.randint(1, 24)):
        needs = rng.sample(pool, rng.choice((0, 0, 0, 1, 1, 2)))
        after = rng.sample(pool, rng.choice((0, 0, 0, 1)))
        priority = rng.choice((None, None, None, 1, -1))
        lines.append(_line(rng.choice(pool), needs, after, priority))
    return "\n".join(lines) + "\n"


def anything(rng):
    pool = [f"w{i}" for i in range(rng.randint(1, 12))]
    lines = []
    for _ in range(rng.randint(0, 20)):
        needs = [rng.choice(pool + ["missing"]) for _ in range(rng.choice((0, 0, 1, 1, 2, 3)))]
        after = [rng.choice(pool + ["absent"]) for _ in range(rng.choice((0, 0, 0, 1, 2)))]
        priority = rng.choice((None, None, 0, 3, -3))
        lines.append(_line(rng.choice(pool), needs, after, priority))
    return "\n".join(lines) + "\n"


def many(seed, count, make, **options):
    rng = random.Random(seed)
    return [make(rng, **options) for _ in range(count)]


def targets_for(rng, text):
    names = sorted({line.split()[0] for line in text.splitlines() if line.strip()}) or ["none"]
    return [rng.choice(names + ["unlisted"] if rng.random() < 0.1 else names)
            for _ in range(rng.randint(1, 3))]


PARSER_PIECES = [
    "a", "b-c", "d_1", "9", "é", ":", ":", "~", "^", "^1", "^-2", "^+3", "^x", '"q r"', '"x\\"y"', '"#:~^"',
    '"', "#c", "# c \\", " ", " ", " ", "\t", "\n", "\n", "\n", "\r\n", "\r", "\\\n", "\\\r\n", "\\", "\x0c",
    "\x0b", "\u2028", "\u00a0", "\x85",
]


def token_soup(seed, count):
    rng = random.Random(seed)
    return ["".join(rng.choice(PARSER_PIECES) for _ in range(rng.randint(0, 14))) for _ in range(count)]
