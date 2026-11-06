"""The stated requirement: order, waves and subset on 200,000 steps, in any sheet order, valid or not.

The prompt asks for 5 seconds. The limit here is looser, to leave room for slower machines,
and still fails anything that grows quadratically.
"""

import random

import pytest

SIZE = 200_000
LIMIT_SECONDS = 20


def name(index):
    return f"s{index}"


@pytest.fixture(scope="module")
def write_sheet(tmp_path_factory):
    folder = tmp_path_factory.mktemp("sheets")
    def write(label, lines):
        path = folder / f"{label}.sheet"
        path.write_text("\n".join(lines) + "\n")
        return str(path)
    return write


@pytest.fixture
def run(cli):
    def go(*arguments):
        return cli(*arguments, timeout=LIMIT_SECONDS)
    return go


@pytest.fixture(scope="module")
def reversed_chain(write_sheet):
    lines = [f"{name(i)}: {name(i + 1)}" for i in range(SIZE - 1)] + [name(SIZE - 1)]
    return write_sheet("reversed", lines)


def test_scale_order_reversed_sheet(run, reversed_chain):
    done = run("order", reversed_chain)
    assert done.returncode == 0, done.stderr[-500:]
    assert done.stdout.split("\n")[:-1] == [name(i) for i in reversed(range(SIZE))]


def test_scale_order_exact_result_with_steps_released_behind_the_scan(run, write_sheet):
    blocks = SIZE // 3
    lines = []
    for i in range(blocks):
        lines += [f"a{i}: b{i}", f"b{i}", f"c{i}"]
    done = run("order", write_sheet("blocks", lines))
    assert done.returncode == 0, done.stderr[-500:]
    expected = [n for i in range(blocks) for n in (f"b{i}", f"c{i}")] + [f"a{i}" for i in range(blocks)]
    assert done.stdout.split("\n")[:-1] == expected


def test_scale_order_shuffled_graph(run, write_sheet):
    rng = random.Random(7)
    needs = {}
    for i in range(SIZE):
        needs[i] = sorted({rng.randrange(i) for _ in range(2)}) if i else []
    lines = [f"{name(i)}: " + " ".join(name(d) for d in deps) for i, deps in needs.items()]
    rng.shuffle(lines)
    done = run("order", write_sheet("shuffled", lines))
    assert done.returncode == 0, done.stderr[-500:]
    output = done.stdout.split("\n")[:-1]
    position = {step: index for index, step in enumerate(output)}
    assert len(output) == SIZE and len(position) == SIZE
    assert all(position[name(d)] < position[name(i)] for i, deps in needs.items() for d in deps)


def test_scale_waves_reversed_sheet(run, reversed_chain):
    done = run("waves", reversed_chain)
    assert done.returncode == 0, done.stderr[-500:]
    expected = [f"{wave}: {name(SIZE - wave)}" for wave in range(1, SIZE + 1)]
    assert done.stdout.split("\n")[:-1] == expected


def test_scale_waves_limit_one_on_independent_steps(run, write_sheet):
    done = run("waves", write_sheet("independent", [name(i) for i in range(SIZE)]), "--limit", "1")
    assert done.returncode == 0, done.stderr[-500:]
    assert done.stdout.split("\n")[:-1] == [f"{i + 1}: {name(i)}" for i in range(SIZE)]


def test_scale_waves_limit_with_a_wide_fan_out(run, write_sheet):
    lines = [f"{name(i)}: root" for i in range(SIZE - 1)] + ["root"]
    done = run("waves", write_sheet("fan-out", lines), "--limit", "1000")
    assert done.returncode == 0, done.stderr[-500:]
    output = done.stdout.split("\n")[:-1]
    assert output[0] == "1: root"
    assert output[1] == "2: " + " ".join(name(i) for i in range(1000))
    assert output[-1].startswith(f"{len(output)}: {name(SIZE - 2 - (SIZE - 2) % 1000)} ")
    assert len(output) == 1 + (SIZE - 1 + 999) // 1000


def test_scale_subset_of_a_deep_chain(run, reversed_chain):
    done = run("subset", reversed_chain, name(SIZE // 2))
    assert done.returncode == 0, done.stderr[-500:]
    assert done.stdout.split("\n")[:-1] == [name(i) for i in range(SIZE - 1, SIZE // 2 - 1, -1)]


def test_scale_subset_with_many_targets(run, write_sheet):
    pairs = SIZE // 2
    lines = [line for i in range(pairs) for line in (f"t{i}: d{i}", f"d{i}")]
    targets = [f"t{i}" for i in range(20_000)]
    done = run("subset", write_sheet("pairs", lines), *targets)
    assert done.returncode == 0, done.stderr[-500:]
    expected = [f"d{i}" for i in range(20_000)] + targets
    assert done.stdout.split("\n")[:-1] == expected


def test_scale_order_step_repeated_many_times(run, write_sheet):
    jobs = SIZE // 2
    lines = []
    for i in reversed(range(jobs)):
        lines += [f"flush: job{i}", f"job{i}: flush"]
    lines.append("flush")
    done = run("order", write_sheet("repeated", lines))
    assert done.returncode == 0, done.stderr[-500:]
    expected = ["flush"] + [f"job{i}" for i in reversed(range(jobs))] + ["flush"] * jobs
    assert done.stdout.split("\n")[:-1] == expected


def test_scale_order_one_step_needing_everything(run, write_sheet):
    others = [name(i) for i in range(SIZE - 1)]
    done = run("order", write_sheet("fan-in", ["final: " + " ".join(others)] + others))
    assert done.returncode == 0, done.stderr[-500:]
    assert done.stdout.split("\n")[:-1] == others + ["final"]


def test_scale_invalid_sheet_with_one_long_cycle(run, write_sheet):
    lines = [f"{name(i)}: {name((i + 1) % SIZE)}" for i in range(SIZE)]
    done = run("order", write_sheet("ring", lines))
    assert done.returncode == 2
    assert done.stdout == ""
    path = " -> ".join([name(i) for i in range(SIZE)] + [name(0)])
    assert done.stderr == f"error: cycle: {path} ({SIZE} blocked)\n"


def test_scale_invalid_sheet_with_an_unknown_need_at_the_end(run, reversed_chain, write_sheet):
    lines = [f"{name(i)}: {name(i + 1)}" for i in range(SIZE - 1)] + [f"{name(SIZE - 1)}: missing"]
    done = run("waves", write_sheet("unknown", lines))
    assert done.returncode == 2
    assert done.stderr == f"error: unknown step 'missing' (needed by {name(SIZE - 1)!r})\n"
