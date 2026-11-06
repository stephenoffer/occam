import json
import resource
import subprocess
import sys
import time

import pytest

LIMIT_SECONDS = 90
LIMIT_RSS_MB = 250
FULL_SIZE = 1_000_000
scale_probe_passed = False


def generate(path, count):
    """Every 7th line repeats an earlier event with attempt=1, so the first occurrence is identifiable."""
    uniques = 0
    with open(path, "w", encoding="utf-8") as handle:
        for n in range(count):
            if n % 7 == 6:
                source = uniques - 1 - (n % 97) if uniques > 97 else uniques - 1
                attempt = 1
            else:
                source, attempt = uniques, 0
                uniques += 1
            handle.write(json.dumps({
                "event_id": f"evt-{source:012d}-{(source * 2654435761) & 0xffffffff:08x}",
                "ts": 1_700_000_000 + (source * 7919) % 86_400,
                "attempt": attempt,
                "source": "api",
                "path": f"/v1/items/{source % 10000}",
                "user": f"u{source % 100000}",
            }) + "\n")
    return uniques


def run_cli(ws, source, target, timeout):
    """Run in a fresh process, so peak RSS reflects this run alone."""
    code = (
        "import resource,subprocess,sys;"
        "p=subprocess.run([sys.executable,'-m','logmerge',sys.argv[1],sys.argv[2]]);"
        "print(p.returncode, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)"
    )
    started = time.monotonic()
    done = subprocess.run([sys.executable, "-c", code, str(source), str(target)], cwd=ws,
                          capture_output=True, text=True, timeout=timeout,
                          env={"PYTHONPATH": str(ws), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    elapsed = time.monotonic() - started
    assert done.returncode == 0, done.stderr
    returncode, rss = done.stdout.split()
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return int(returncode), elapsed, int(rss) / divisor


def test_exact_semantics_on_tricky_small_input(ws, tmp_path):
    source, target = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    source.write_text("\n".join([
        '{"event_id":"b","ts":2,"v":"first"}',
        '',
        '{"event_id":"a","ts":2,"z":"Zürich ☃","v":"first"}',
        '{"event_id":"c","ts":1.5,"v":"first"}',
        '{"event_id":"a","ts":9,"v":"second"}',
        '{"event_id":"10","ts":2,"v":"first"}',
        '{"event_id":"9","ts":2,"v":"first"}',
    ]) + "\n", encoding="utf-8")
    code, _, _ = run_cli(ws, source, target, 60)
    assert code == 0
    assert target.read_text(encoding="utf-8").splitlines() == [
        '{"event_id": "c", "ts": 1.5, "v": "first"}',
        '{"event_id": "10", "ts": 2, "v": "first"}',
        '{"event_id": "9", "ts": 2, "v": "first"}',
        '{"event_id": "a", "ts": 2, "v": "first", "z": "Zürich ☃"}',
        '{"event_id": "b", "ts": 2, "v": "first"}',
    ]


def test_empty_input(ws, tmp_path):
    source, target = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    source.write_text("")
    code, _, _ = run_cli(ws, source, target, 60)
    assert code == 0
    assert target.read_text() == ""


def test_output_may_be_the_input_file(ws, tmp_path):
    path = tmp_path / "same.jsonl"
    path.write_text('{"event_id":"b","ts":2}\n{"event_id":"a","ts":1}\n{"event_id":"b","ts":9}\n')
    code, _, _ = run_cli(ws, path, path, 60)
    assert code == 0
    assert path.read_text().splitlines() == ['{"event_id": "a", "ts": 1}', '{"event_id": "b", "ts": 2}']


def test_failed_run_leaves_existing_output_untouched(ws, tmp_path):
    source, target = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    target.write_text("previous good output\n")
    source.write_text('{"event_id":"a","ts":1}\n' * 3 + "this line is not json\n")
    code, _, _ = run_cli(ws, source, target, 60)
    assert code != 0, "bad input must exit non-zero"
    assert target.read_text() == "previous good output\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.jsonl", "out.jsonl"], "temporary files left next to the output"


def test_scales_past_quadratic(ws, tmp_path):
    """Fails fast on quadratic work, before spending time at full size."""
    source, target = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    generate(source, 50_000)
    run_cli(ws, source, target, 30)
    global scale_probe_passed
    scale_probe_passed = True


@pytest.fixture(scope="module")
def full_run(ws, tmp_path_factory):
    assert scale_probe_passed, "already too slow at 50,000 records, so the full size is not attempted"
    folder = tmp_path_factory.mktemp("full")
    source, target = folder / "in.jsonl", folder / "out.jsonl"
    uniques = generate(source, FULL_SIZE)
    code, elapsed, rss = run_cli(ws, source, target, LIMIT_SECONDS * 2)
    return {"code": code, "elapsed": elapsed, "rss": rss, "target": target, "uniques": uniques}


def test_full_size_within_time(full_run):
    assert full_run["code"] == 0
    assert full_run["elapsed"] < LIMIT_SECONDS, f"{full_run['elapsed']:.0f}s"


def test_full_size_within_memory(full_run):
    assert full_run["rss"] < LIMIT_RSS_MB, f"{full_run['rss']:.0f} MB"


def test_full_size_output_equivalent(full_run):
    previous = (float("-inf"), "")
    seen = set()
    count = 0
    with open(full_run["target"], encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            key = (record["ts"], record["event_id"])
            assert key > previous, "must be sorted by ts then event_id, with no duplicates"
            assert record["attempt"] == 0, "the first occurrence must win"
            previous = key
            count += 1
    assert count == full_run["uniques"]
