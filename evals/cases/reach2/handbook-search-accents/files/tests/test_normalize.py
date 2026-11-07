from textproc.normalize import fold


def test_case_is_folded():
    assert fold("Laptop") == fold("LAPTOP") == "laptop"


def test_casefold_handles_sharp_s():
    assert fold("Straße") == fold("STRASSE")


def test_edge_punctuation_is_trimmed():
    assert fold("(laptop),") == "laptop"
    assert fold("--") == ""


def test_apostrophes_are_dropped():
    assert fold("don't") == fold("dont") == fold("don’t")


def test_inner_hyphen_is_kept():
    assert fold("two-factor") == "two-factor"
