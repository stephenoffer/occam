import json

from indexing import store
from indexing.entry import Entry
from indexing.store import Index


def _entry(**counts):
    return Entry(digest="abc", title="T", tags=("x",), owner="o", length=sum(counts.values()), counts=counts,
                 title_terms=("t",))


def test_round_trip(tmp_path):
    index = Index({"a.md": _entry(laptop=2, desk=1)}, built_at="2026-11-01T09:00:00+00:00")
    store.save(tmp_path, index)
    loaded = store.load(tmp_path)
    assert loaded.entries["a.md"].counts == {"laptop": 2, "desk": 1}
    assert loaded.built_at == "2026-11-01T09:00:00+00:00"


def test_missing_index_is_none(tmp_path):
    assert store.load(tmp_path) is None


def test_other_layout_is_treated_as_absent(tmp_path):
    store.save(tmp_path, Index({"a.md": _entry(laptop=1)}))
    path = store.path_for(tmp_path)
    raw = json.loads(path.read_text())
    raw["layout"] = store.LAYOUT - 1
    path.write_text(json.dumps(raw))
    assert store.load(tmp_path) is None


def test_corrupt_index_is_treated_as_absent(tmp_path):
    path = store.path_for(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert store.load(tmp_path) is None


def test_save_leaves_no_temporary_files(tmp_path):
    store.save(tmp_path, Index({"a.md": _entry(laptop=1)}))
    assert [p.name for p in store.path_for(tmp_path).parent.iterdir()] == ["index.json"]
