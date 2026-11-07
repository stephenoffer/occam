"""The sample handbook in this repository stays searchable."""

from pathlib import Path

from corpus import iter_paths
from query import search

HANDBOOK = Path(__file__).resolve().parents[1] / "handbook"


def test_drafts_are_ignored():
    assert not any(path.startswith("drafts/") for path in iter_paths(HANDBOOK))


def test_every_page_has_an_owner():
    from corpus import read_document
    assert all(read_document(HANDBOOK, path).owner for path in iter_paths(HANDBOOK))


def test_common_searches():
    assert search(HANDBOOK, "laptop")[0].path == "it/laptops.md"
    assert search(HANDBOOK, "expense receipt")[0].path == "people/expenses.md"
    assert search(HANDBOOK, "title:office")
