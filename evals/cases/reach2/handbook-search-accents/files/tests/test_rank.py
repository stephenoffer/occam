from indexing.entry import Entry
from query.rank import idf, score


def _entry(length, counts, title_terms=()):
    return Entry(digest="", title="", tags=(), owner="", length=length, counts=counts, title_terms=title_terms)


def test_rarer_terms_weigh_more():
    assert idf(1, 100) > idf(50, 100)


def test_more_occurrences_score_higher():
    frequencies = {"laptop": 2}
    once = score(_entry(10, {"laptop": 1}), ["laptop"], frequencies, 10, 10)
    thrice = score(_entry(10, {"laptop": 3}), ["laptop"], frequencies, 10, 10)
    assert thrice > once


def test_title_terms_are_boosted():
    frequencies = {"laptop": 2}
    plain = score(_entry(10, {"laptop": 1}), ["laptop"], frequencies, 10, 10)
    titled = score(_entry(10, {"laptop": 1}, ("laptop",)), ["laptop"], frequencies, 10, 10)
    assert titled > plain


def test_missing_terms_score_nothing():
    assert score(_entry(10, {"desk": 1}), ["laptop"], {"laptop": 1}, 10, 10) == 0.0
