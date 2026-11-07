from textproc.terms import term, terms, words


def test_words_keep_original_spelling():
    assert list(words("New starters: Laptops!")) == ["New", "starters", "Laptops"]


def test_terms_fold_stem_and_drop_stopwords():
    assert terms("The Laptops are refreshed") == ["laptop", "refresh"]


def test_term_of_a_stopword_is_none():
    assert term("the") is None
    assert term("...") is None


def test_numbers_are_terms():
    assert terms("open 08:00 to 15:00") == ["open", "08", "00", "15", "00"]


def test_repeats_are_kept_in_order():
    assert terms("laptop desk laptop") == ["laptop", "desk", "laptop"]
