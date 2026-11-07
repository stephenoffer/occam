from query.parse import parse


def test_plain_words_become_required_terms():
    query = parse("Laptops refresh")
    assert query.required == ["laptop", "refresh"]
    assert query.highlight == ["Laptops", "refresh"]


def test_phrases_exclusions_and_fields():
    query = parse('"expense claim" -taxi tag:Money title:office')
    assert query.phrases == [["expense", "claim"]]
    assert query.required == ["expense", "claim"]
    assert query.excluded == ["taxi"]
    assert query.tags == ["money"]
    assert query.title_terms == ["office"]


def test_unknown_field_is_an_ordinary_word():
    assert parse("owner:finance").required == ["owner", "finance"]


def test_only_stopwords_is_empty():
    assert parse("how do the").is_empty


def test_repeated_words_count_once():
    assert parse("laptop laptops").required == ["laptop"]
