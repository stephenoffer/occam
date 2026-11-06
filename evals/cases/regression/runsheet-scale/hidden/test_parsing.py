"""parse() gives what the original gave, and reports the same problems at the same lines."""

import pytest

import sheets


def parses(*texts):
    return [{"op": "parse", "text": text} for text in texts]


def test_quoted_names_and_escapes(same_as_original):
    same_as_original(parses(
        '"a b": "c d" ~"e f" ^2\n',
        '"a\\"b"\n',
        '"a\\\\b": "c"\n',
        '"a\\nb"\n',
        '"#:~^": x\n',
        '"": a\n',
        '"tab\there"\n',
    ))


def test_tokens_need_no_spaces_between_them(same_as_original):
    same_as_original(parses('a:b~c^1\n', 'a:"b"c\n', 'a"b"\n', '"a""b"\n', "a~b:c\n"))


def test_comments_start_anywhere_outside_quotes(same_as_original):
    same_as_original(parses("a#b\nc\n", "a: b#c d\ne\n", '"a#b": c # d\n', "# one \\\nb\n", "a # b \\\nc\n"))


def test_joined_lines(same_as_original):
    same_as_original(parses(
        "a: b \\\n  c\nd\n",
        "a: b \\\r\n  c\r\nd\r\n",
        "a\\\n",
        "a \\\n\\\n b\n",
        "\\\n\\\na\n",
        "a: \\\n# still a comment\nb\n",
    ))


def test_a_backslash_anywhere_else_is_an_error(same_as_original):
    same_as_original(parses("a \\", "a\\b\n", "a \\ \nb\n", "\\"))


def test_priority_forms(same_as_original):
    same_as_original(parses(
        "a ^-2\n", "a ^+3\n", "a ^ 4\n", 'a ^"5"\n', "a ^1_000\n", "a ^1 ^2\n", "a: b ^3 c\n",
        "a ^x\n", "a ^\n", "a ^1.5\n", "a ^:\n", "^1\n", "a ^~b\n",
    ))


def test_preference_forms(same_as_original):
    same_as_original(parses(
        "a ~b\n", "a ~ b\n", 'a: ~"b c"\n', "a ~b: c\n", "a ~\n", "a ~:\n", "a ~~b\n", "~a\n",
    ))


def test_colon_forms(same_as_original):
    same_as_original(parses("a:b\n", "a:\n", "a : b\n", "a::b\n", ":a\n", "a: b: c\n", ":\n"))


def test_needs_a_colon_before_names(same_as_original):
    same_as_original(parses("a b\n", 'a "b"\n', "a\tb\n"))


def test_stray_characters_are_rejected(same_as_original):
    same_as_original(parses(
        '"unterminated\n', 'a: "unterminated', 'a"\n', '"a\\\nb"\n', "a\rb\n", "a\x0cb\n", "a\u00a0b\n",
        "a\x0bb\n", "a\u2028b\n", "a\x85b\n", "a\x1cb\n", "\r",
    ))


def test_only_a_newline_ends_a_line(same_as_original):
    same_as_original(parses(
        "# one\x0ctwo\na\n",
        "# one\u2028two: three\na\n",
        "# one\x85two\n",
        '"a\u2028b"\n',
        '"a\x0cb": "c\x85d"\n',
        '"a\rb"\n',
        "# one\rtwo\na\n",
    ))


def test_line_endings(same_as_original):
    same_as_original(parses("a\r\nb: a\r\n", "a\r\n\r\nb\r\n", "a\n\r\nb", "a\r\r\n"))


def test_line_numbers_count_every_physical_line(same_as_original):
    same_as_original(parses(
        "a\n\n# c\nb c\n",
        "a \\\n b \\\n c\nd e\n",
        "a: \\\n b \\\n : c\n",
        "a\r\n\r\nb c\r\n",
        "a\n\n\n\"oops\n",
        "a \\\n\"oops\n",
    ))


def test_which_problem_gets_reported_first(same_as_original):
    same_as_original(parses('a b\n"oops\n', 'a b "oops\n', 'a ^x ~\n', "a ~ ^x\n", "a b\nc d\n", '"oops\na b\n'))


def test_unicode_names(same_as_original):
    same_as_original(parses("déploy: naïve ~日本語\nnaïve\n", "数据 ^3\n"))


@pytest.mark.parametrize("seed", [501, 502, 503])
def test_parse_random_token_soup(same_as_original, seed):
    same_as_original(parses(*sheets.token_soup(seed, 700)))
