from corpus.frontmatter import parse_list, split


def test_fields_and_body_are_split():
    fields, body = split("---\ntitle: Laptops\nowner: it\n---\nBody text\n")
    assert fields == {"title": "Laptops", "owner": "it"}
    assert body == "Body text\n"


def test_page_without_front_matter_is_all_body():
    assert split("# Heading\ntext") == ({}, "# Heading\ntext")


def test_unterminated_header_is_left_in_the_body():
    text = "---\ntitle: Broken\nno end"
    assert split(text) == ({}, text)


def test_quoted_values_are_unquoted():
    assert split('---\ntitle: "Café: hours"\n---\n')[0]["title"] == "Café: hours"


def test_lists_in_both_spellings():
    assert parse_list("[it, equipment]") == ("it", "equipment")
    assert parse_list("it, , equipment") == ("it", "equipment")
    assert parse_list("") == ()
