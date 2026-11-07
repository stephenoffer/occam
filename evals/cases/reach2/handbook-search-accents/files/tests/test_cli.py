import json

from findoc.cli import main


def test_search_json(small_handbook, capsys):
    assert main(["search", str(small_handbook), "laptops", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["query"] == "laptops"
    assert [r["path"] for r in out["results"]] == ["it/laptops.md"]
    assert set(out["results"][0]) == {"path", "title", "owner", "score", "snippet"}


def test_search_text_without_results(small_handbook, capsys):
    assert main(["search", str(small_handbook), "submarine"]) == 0
    assert capsys.readouterr().out.strip() == "no matching pages"


def test_query_words_are_joined(small_handbook, capsys):
    main(["search", str(small_handbook), "booking", "money", "--json"])
    assert json.loads(capsys.readouterr().out)["query"] == "booking money"


def test_reindex_then_stats(small_handbook, capsys):
    assert main(["reindex", str(small_handbook)]) == 0
    assert capsys.readouterr().out.startswith("indexed 4 pages")
    assert main(["stats", str(small_handbook), "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["saved"] is True and stats["pages"] == 4
    assert stats["pages_by_owner"] == {"facilities": 1, "finance": 2, "it-support": 1}


def test_missing_root_is_an_error(tmp_path, capsys):
    assert main(["search", str(tmp_path / "nope"), "x"]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_limit_from_settings_file(small_handbook, capsys):
    (small_handbook / ".findocrc").write_text("[search]\nlimit = 1\n")
    main(["search", str(small_handbook), "tag:money", "--json"])
    assert len(json.loads(capsys.readouterr().out)["results"]) == 1
