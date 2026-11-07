from textproc.snippets import ELLIPSIS, find_matches, plain, snippet


def test_plain_drops_markdown_markers():
    assert plain("# Title\n\nSee [the page](x.md) and **bold** `code`.") == "Title See the page and bold code."


def test_query_words_are_marked_ignoring_case():
    assert snippet("Laptops are refreshed.", ["laptop"]) == "**Laptops** are refreshed."


def test_matches_ignore_accents_and_keep_the_original_text():
    assert snippet("The Café opens at eight.", ["cafe"]) == "The **Café** opens at eight."
    assert snippet("the cafe over the road", ["Café"]) == "the **cafe** over the road"
    assert snippet("Zürich HB", ["ZURICH"]) == "**Zürich** HB"


def test_decomposed_accents_and_expanding_letters_keep_their_place():
    assert snippet("Cafe\u0301 on Straße 5", ["cafe", "strasse"]) == "**Cafe\u0301** on **Straße** 5"


def test_matches_start_at_word_boundaries():
    assert find_matches("a desktop and a laptop", ["top"]) == []


def test_window_moves_to_the_densest_part():
    text = "intro " * 80 + "the laptop and the laptop bag " + "outro " * 80
    result = snippet(text, ["laptop"], width=80)
    assert result.count("**laptop**") == 2
    assert result.startswith(ELLIPSIS) and result.endswith(ELLIPSIS)


def test_no_match_shows_the_start():
    assert snippet("Short page.", ["missing"]) == "Short page."


def test_words_are_not_cut_at_the_end():
    result = snippet("alpha beta gamma delta epsilon", ["alpha"], width=14)
    assert result == "**alpha** beta" + ELLIPSIS
