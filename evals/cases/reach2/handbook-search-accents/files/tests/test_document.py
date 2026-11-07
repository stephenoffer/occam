from corpus.document import digest_of, parse_document, read_document


def test_title_prefers_front_matter(make_tree):
    root = make_tree({"a.md": "---\ntitle: From header\n---\n# From heading\n"})
    assert read_document(root, "a.md").title == "From header"


def test_title_falls_back_to_heading_then_file_name():
    assert parse_document("x/a.md", b"# Big heading\ntext").title == "Big heading"
    assert parse_document("x/annual-leave.md", b"text").title == "Annual leave"


def test_tags_are_lowercased_and_owner_kept():
    document = parse_document("a.md", b"---\ntags: [IT, Equipment]\nowner: it-support\n---\nbody")
    assert document.tags == ("it", "equipment")
    assert document.owner == "it-support"


def test_digest_changes_with_content():
    assert parse_document("a.md", b"one").digest == digest_of(b"one") != digest_of(b"two")


def test_byte_order_mark_is_ignored():
    assert parse_document("a.md", "﻿# Title\n".encode("utf-8")).title == "Title"
