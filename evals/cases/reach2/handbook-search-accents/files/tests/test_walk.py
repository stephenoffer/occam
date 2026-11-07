from corpus.walk import iter_paths


def test_pages_are_listed_sorted_and_relative(make_tree):
    root = make_tree({"b.md": "", "a/z.txt": "", "a/y.markdown": "", "notes.pdf": ""})
    assert list(iter_paths(root)) == ["b.md", "a/y.markdown", "a/z.txt"]


def test_hidden_directories_are_skipped(make_tree):
    root = make_tree({".findoc/index.md": "", ".git/x.md": "", "page.md": ""})
    assert list(iter_paths(root)) == ["page.md"]


def test_ignore_file_patterns(make_tree):
    root = make_tree({
        ".findocignore": "# comment\ndrafts/\n*.tmp.md\n",
        "drafts/a.md": "",
        "keep.md": "",
        "scratch.tmp.md": "",
        "sub/other.tmp.md": "",
    })
    assert list(iter_paths(root)) == ["keep.md"]
