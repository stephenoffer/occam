from indexing import build
from query import search


def _paths(hits):
    return [hit.path for hit in hits]


def test_plural_and_case_match(small_handbook):
    assert _paths(search(small_handbook, "LAPTOP")) == ["it/laptops.md"]


def test_every_word_is_required(small_handbook):
    assert _paths(search(small_handbook, "booking money")) == ["travel/booking.md"]
    assert search(small_handbook, "booking laptop") == []


def test_ignored_pages_are_not_searched(small_handbook):
    assert "drafts/secret.md" not in _paths(search(small_handbook, "laptops"))


def test_tag_title_and_exclusion(small_handbook):
    assert sorted(_paths(search(small_handbook, "tag:money"))) == ["people/expenses.md", "travel/booking.md"]
    assert _paths(search(small_handbook, "title:office")) == ["office/london.md"]
    assert _paths(search(small_handbook, "money -taxi")) == ["travel/booking.md"]


def test_phrase_needs_adjacent_words(small_handbook):
    assert _paths(search(small_handbook, '"expense claim"')) == ["people/expenses.md"]
    assert search(small_handbook, '"claim expense"') == []


def test_saved_index_and_reading_pages_agree(small_handbook):
    before = search(small_handbook, "travel")
    build.update(small_handbook)
    assert search(small_handbook, "travel") == before


def test_snippet_marks_the_match(small_handbook):
    [hit] = search(small_handbook, "fridge")
    assert "**fridge**" in hit.snippet
    assert hit.title == "London office" and hit.owner == "facilities"


def test_accents_are_ignored_both_ways(make_tree):
    root = make_tree({"a.md": "# Café hours\nThe Café opens at 8.", "b.md": "# Snacks\nThe cafe over the road.",
                      "c.md": "# Zürich office\nNear the station."})
    assert sorted(_paths(search(root, "cafe"))) == ["a.md", "b.md"]
    assert sorted(_paths(search(root, "CAFÉ"))) == ["a.md", "b.md"]
    assert _paths(search(root, "zurich")) == ["c.md"]
    build.update(root)
    assert sorted(_paths(search(root, "café"))) == ["a.md", "b.md"]
    assert "**Café**" in search(root, "cafe hours")[0].snippet


def test_limit(small_handbook):
    assert len(search(small_handbook, "tag:money", limit=1)) == 1


def test_page_deleted_after_reindex_is_skipped(small_handbook):
    build.update(small_handbook)
    (small_handbook / "it/laptops.md").unlink()
    assert search(small_handbook, "laptop") == []
