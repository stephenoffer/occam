import pytest

from runsheet import ParseError, Step, parse


def test_plain_steps():
    assert parse("snapshot\nmigrate: snapshot\n") == [
        Step("snapshot"),
        Step("migrate", needs=("snapshot",)),
    ]


def test_preference_and_priority():
    assert parse("web: migrate ~warm ^5\n") == [
        Step("web", needs=("migrate",), after=("warm",), priority=5),
    ]


def test_comments_and_blank_lines_are_skipped():
    assert parse("# heading\n\nsnapshot # first\n") == [Step("snapshot")]


def test_quoted_name():
    assert parse('"smoke test eu": web\n') == [Step("smoke test eu", needs=("web",))]


def test_missing_trailing_newline():
    assert parse("snapshot") == [Step("snapshot")]


def test_error_reports_the_line():
    with pytest.raises(ParseError) as caught:
        parse("snapshot\nmigrate snapshot\n")
    assert caught.value.line == 2
