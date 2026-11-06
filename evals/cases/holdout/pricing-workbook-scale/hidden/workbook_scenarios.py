"""Scenarios run in a child process, so a hang or a crash cannot take the suite with it.

usage: workbook_scenarios.py <scenario> [argument]    prints one JSON result as the last line
"""

import json
import math
import random
import sys
import time

from pricemodel import CircularReference, Workbook

CHAIN_LENGTH = 30_000
LADDER_DEPTH = 64
ROLLUP_LEAVES = 50_000
EDIT_ROUNDS = 2_000
EDIT_BUDGET_SECONDS = 20.0  # twice the 5 ms average the prompt asks for


def chain_cells(length=CHAIN_LENGTH):
    cells = [("chain.0", 1)]
    cells += [(f"chain.{i}", f"=chain.{i - 1} + 1") for i in range(1, length)]
    return cells


def rollup_cells(leaves=ROLLUP_LEAVES):
    cells = [(f"item.{i}", 1) for i in range(leaves)]
    level = [name for name, _ in cells]
    depth = 0
    while len(level) > 1:
        above = []
        for start in range(0, len(level), 10):
            name = f"sub.{depth}.{start // 10}"
            cells.append((name, "=SUM(" + ", ".join(level[start:start + 10]) + ")"))
            above.append(name)
        level = above
        depth += 1
    cells.append(("rollup.total", f"={level[0]}"))
    return cells


def ladder_cells(depth=LADDER_DEPTH):
    cells = [("rung.base", 1), ("rung.0.a", "=rung.base"), ("rung.0.b", "=rung.base")]
    for i in range(1, depth):
        for side in "ab":
            cells.append((f"rung.{i}.{side}", f"=rung.{i - 1}.a + rung.{i - 1}.b"))
    return cells


def load(workbook, cells, order, seed=7):
    cells = list(cells)
    if order == "reverse":
        cells.reverse()
    elif order == "shuffled":
        random.Random(seed).shuffle(cells)
    for name, value in cells:
        workbook.set(name, value)


def long_chain(order):
    wb = Workbook()
    load(wb, chain_cells(), order)
    last = f"chain.{CHAIN_LENGTH - 1}"
    seen = [wb.get(last), wb.get(f"chain.{CHAIN_LENGTH // 2}")]
    for value in (5, 9, -2):
        wb.set("chain.0", value)
        seen.append(wb.get(last))
    return {"seen": seen, "expected": [
        CHAIN_LENGTH, CHAIN_LENGTH // 2 + 1,
        CHAIN_LENGTH + 4, CHAIN_LENGTH + 8, CHAIN_LENGTH - 3,
    ]}


def shared_subtotals(order):
    wb = Workbook()
    load(wb, ladder_cells(), order)
    top = f"rung.{LADDER_DEPTH - 1}.a"
    seen, expected = [wb.get(top)], [2.0 ** (LADDER_DEPTH - 1)]
    rng = random.Random(11)
    for _ in range(200):
        base = rng.randrange(1, 1000)
        wb.set("rung.base", base)
        seen.append(wb.get(top))
        expected.append(base * 2.0 ** (LADDER_DEPTH - 1))
    wb.set("rung.3.b", 0)
    wb.set("rung.base", 1)
    seen.append(wb.get("rung.4.a"))
    expected.append(8.0)
    return {"seen": seen, "expected": expected}


def what_if(order):
    wb = Workbook()
    load(wb, rollup_cells(), order)
    wb.set("knob", 3)
    if wb.get("rollup.total") != ROLLUP_LEAVES:
        return {"wrong": f"first read gave {wb.get('rollup.total')}"}

    rng = random.Random(23)
    knob = 3
    numbers = dict.fromkeys(range(ROLLUP_LEAVES), 1)
    doubled = set()
    total = ROLLUP_LEAVES

    started = time.perf_counter()
    for round_number in range(EDIT_ROUNDS):
        leaf = rng.randrange(ROLLUP_LEAVES)
        if round_number % 100 == 99:
            new_knob = rng.randrange(1, 50)
            total += 2 * (new_knob - knob) * len(doubled)
            knob = new_knob
            wb.set("knob", knob)
        elif round_number % 25 == 24:
            total -= 2 * knob if leaf in doubled else numbers[leaf]
            numbers.pop(leaf, None)
            doubled.add(leaf)
            total += 2 * knob
            wb.set(f"item.{leaf}", "=knob * 2")
        else:
            total -= 2 * knob if leaf in doubled else numbers[leaf]
            doubled.discard(leaf)
            numbers[leaf] = rng.randrange(0, 100)
            total += numbers[leaf]
            wb.set(f"item.{leaf}", numbers[leaf])

        value = wb.get("rollup.total")
        if value != total:
            return {"wrong": f"after edit {round_number} the total read {value}, expected {total}"}
        if time.perf_counter() - started > EDIT_BUDGET_SECONDS:
            return {"over_budget": f"only {round_number + 1} of {EDIT_ROUNDS} rounds in {EDIT_BUDGET_SECONDS}s"}
    return {"seconds": time.perf_counter() - started}


def forward_references(_):
    wb = Workbook()
    wb.set("a", "=b + 1")
    wb.set("b", "=c + 1")
    seen = [wb.get("a")]
    wb.set("c", 5)
    seen.append(wb.get("a"))
    wb.set("c", 6)
    seen.append(wb.get("a"))
    wb.set("b", 1)
    seen.append(wb.get("a"))
    return {"seen": seen, "expected": [2.0, 7.0, 8.0, 2.0]}


def rewiring(_):
    wb = Workbook()
    wb.set("left", 1)
    wb.set("right", 100)
    wb.set("pick", "=left + 1")
    wb.set("downstream", "=pick * 2")
    seen = [wb.get("downstream")]
    wb.set("pick", "=right + 1")
    seen.append(wb.get("downstream"))
    wb.set("right", 200)
    seen.append(wb.get("downstream"))
    wb.set("left", 7)
    seen.append(wb.get("downstream"))
    wb.set("pick", 3)
    seen.append(wb.get("downstream"))
    wb.set("right", 300)
    wb.set("left", 8)
    seen.append(wb.get("downstream"))
    wb.set("pick", "=left")
    seen.append(wb.get("downstream"))
    return {"seen": seen, "expected": [4.0, 202.0, 402.0, 402.0, 6.0, 6.0, 16.0]}


def attempt_cycle(wb, assignments, reader):
    """Apply edits and read. Returns True if CircularReference surfaced from set or get."""
    try:
        for name, value in assignments:
            wb.set(name, value)
        wb.get(reader)
    except CircularReference:
        return True
    return False


def long_cycle(_):
    wb = Workbook()
    for name, value in chain_cells():
        wb.set(name, value)
    wb.get(f"chain.{CHAIN_LENGTH - 1}")
    reported = attempt_cycle(wb, [("chain.0", f"=chain.{CHAIN_LENGTH - 1} + 1")], "chain.5")
    wb.set("elsewhere", 4)
    unrelated = wb.get("elsewhere")
    wb.set("chain.0", 1)
    return {"reported": reported, "unrelated": unrelated, "after": wb.get(f"chain.{CHAIN_LENGTH - 1}"),
            "expected_after": CHAIN_LENGTH}


def short_cycles(_):
    wb = Workbook()
    wb.set("a", 1)
    wb.set("b", "=a + 1")
    first = wb.get("b")
    introduced = attempt_cycle(wb, [("a", "=b + 1")], "b")
    wb.set("a", 5)
    recovered = wb.get("b")
    self_loop = attempt_cycle(wb, [("self", "=self + 1")], "self")
    wb.set("self", 2)
    return {"first": first, "introduced": introduced, "recovered": recovered,
            "self_loop": self_loop, "self_after": wb.get("self")}


def errors(_):
    wb = Workbook()
    wb.set("units", 0)
    wb.set("unit_cost", "=100 / units")
    wb.set("doubled", "=unit_cost * 2")
    wb.set("guarded", "=IF(units = 0, -1, unit_cost)")
    raised = []
    for _ in range(2):
        try:
            wb.get("doubled")
            raised.append(False)
        except ZeroDivisionError:
            raised.append(True)
    seen = [wb.get("guarded")]
    wb.set("units", 4)
    seen += [wb.get("doubled"), wb.get("guarded")]
    wb.set("units", 0)
    seen.append(wb.get("guarded"))
    try:
        wb.get("unit_cost")
        raised.append(False)
    except ZeroDivisionError:
        raised.append(True)
    wb.set("units", 5)
    seen.append(wb.get("doubled"))
    return {"raised": raised, "seen": seen, "expected": [-1.0, 50.0, 25.0, -1.0, 40.0]}


def random_edits(_):
    """Random edits and reads, checked against an independent evaluation of the current contents."""
    rng = random.Random(31)
    size = 250
    contents = {}

    def random_content(index):
        if index < 5 or rng.random() < 0.3:
            return ("number", rng.randrange(-20, 20))
        refs = [f"r{rng.randrange(index)}" for _ in range(rng.randrange(1, 4))]
        return (rng.choice(["sum", "scaled", "if"]), refs)

    def as_cell(content):
        kind, payload = content
        if kind == "number":
            return payload
        if kind == "sum":
            return "=SUM(" + ", ".join(payload) + ")"
        if kind == "scaled":
            return "=(" + " + ".join(payload) + ") * 0.5"
        return f"=IF({payload[0]} > 0, {payload[-1]}, 1)"

    def oracle(name, memo):
        if name in memo:
            return memo[name]
        kind, payload = contents[name]
        if kind == "number":
            value = float(payload)
        elif kind == "sum":
            value = sum(oracle(ref, memo) for ref in payload)
        elif kind == "scaled":
            value = sum(oracle(ref, memo) for ref in payload) * 0.5
        else:
            value = oracle(payload[-1], memo) if oracle(payload[0], memo) > 0 else 1.0
        memo[name] = value
        return value

    wb = Workbook()
    order = list(range(size))
    rng.shuffle(order)
    for index in order:
        name = f"r{index}"
        contents[name] = random_content(index)
        wb.set(name, as_cell(contents[name]))

    for step in range(3000):
        for _ in range(rng.randrange(0, 4)):
            index = rng.randrange(size)
            name = f"r{index}"
            contents[name] = random_content(index)
            wb.set(name, as_cell(contents[name]))
        memo = {}
        for _ in range(rng.randrange(1, 4)):
            name = f"r{rng.randrange(size)}"
            actual, expected = wb.get(name), oracle(name, memo)
            if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9):
                return {"wrong": f"step {step}: {name} read {actual}, expected {expected}"}
    return {"ok": True}


def write_model(path):
    """Write a model about the size the prompt describes, in shuffled order."""
    cells = chain_cells() + ladder_cells() + rollup_cells(25_000)
    random.Random(41).shuffle(cells)
    with open(path, "w") as handle:
        json.dump({"cells": dict(cells)}, handle)
    return {"cells": len(cells)}


def write_cycle_model(path):
    cells = chain_cells()
    cells[0] = ("chain.0", f"=chain.{CHAIN_LENGTH - 1} + 1")
    with open(path, "w") as handle:
        json.dump({"cells": dict(cells)}, handle)
    return {"cells": len(cells)}


SCENARIOS = {f.__name__: f for f in (
    long_chain, shared_subtotals, what_if, forward_references, rewiring, long_cycle,
    short_cycles, errors, random_edits, write_model, write_cycle_model,
)}

if __name__ == "__main__":
    scenario = SCENARIOS[sys.argv[1]]
    print("\n" + json.dumps(scenario(sys.argv[2] if len(sys.argv) > 2 else None)))
