import json

from logmerge.pipeline import run


def test_dedupes_and_sorts(tmp_path):
    source = tmp_path / "in.jsonl"
    target = tmp_path / "out.jsonl"
    source.write_text(
        '{"event_id":"b","ts":2}\n{"event_id":"a","ts":2}\n{"event_id":"c","ts":1}\n{"event_id":"a","ts":2,"dup":true}\n'
    )
    run(str(source), str(target))
    assert [json.loads(line)["event_id"] for line in target.read_text().splitlines()] == ["c", "a", "b"]
