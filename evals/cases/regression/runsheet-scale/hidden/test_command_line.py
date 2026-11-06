"""The command line prints what the original printed, with the same exit status."""

import pytest

BEHIND_THE_SCAN = "a: b\nb\nc ^0\nd: a\n"
PRIORITIES = "gate\nhi: gate ^5\nmid ^1\nlow\n"
SPACES = '"smoke test": "pre flight"\n"pre flight"\nother\n'
CYCLE = "x: a\nz: a ^5\na: b\nb: a\nok\n"
UNKNOWN = "a: nope\nb\n"
MALFORMED = 'a\nb c\n"oops\n'


def assert_same(got, expected):
    assert (got.returncode, got.stdout, got.stderr) == (expected.returncode, expected.stdout, expected.stderr)


@pytest.mark.parametrize("arguments,sheet", [
    (["order", "-"], BEHIND_THE_SCAN),
    (["order", "-"], PRIORITIES),
    (["order", "-"], SPACES),
    (["order", "-"], ""),
    (["waves", "-"], BEHIND_THE_SCAN),
    (["waves", "-"], SPACES),
    (["waves", "-"], ""),
    (["waves", "-", "--limit", "1"], PRIORITIES),
    (["waves", "-", "--limit", "2"], PRIORITIES),
    (["waves", "--limit", "2", "-"], BEHIND_THE_SCAN),
    (["subset", "-", "d"], BEHIND_THE_SCAN),
    (["subset", "-", "smoke test"], SPACES),
    (["subset", "-", "hi", "low"], PRIORITIES),
])
def test_cli_output(cli, original_cli, arguments, sheet):
    assert_same(cli(*arguments, stdin=sheet), original_cli(*arguments, stdin=sheet))


@pytest.mark.parametrize("arguments,sheet", [
    (["order", "-"], CYCLE),
    (["order", "-"], UNKNOWN),
    (["order", "-"], MALFORMED),
    (["waves", "-"], CYCLE),
    (["waves", "-", "--limit", "1"], CYCLE),
    (["waves", "-"], UNKNOWN),
    (["subset", "-", "nope"], "a\n"),
    (["subset", "-", "a"], UNKNOWN),
    (["subset", "-", "b"], UNKNOWN),
    (["subset", "-", "x", "z"], CYCLE),
])
def test_cli_errors(cli, original_cli, arguments, sheet):
    assert_same(cli(*arguments, stdin=sheet), original_cli(*arguments, stdin=sheet))


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_cli_limit_below_one(cli, original_cli, limit):
    for sheet in ("a\nb: a\n", "", "a: b\nb: a\n"):
        assert_same(cli("waves", "-", "--limit", limit, stdin=sheet),
                    original_cli("waves", "-", "--limit", limit, stdin=sheet))


def test_cli_prints_nothing_to_stdout_when_a_plan_fails_late(cli, original_cli):
    sheet = "a\nb: a\nc: d\nd: c\n"
    for arguments in (["order", "-"], ["waves", "-"], ["subset", "-", "b", "c"]):
        got = cli(*arguments, stdin=sheet)
        assert got.stdout == ""
        assert_same(got, original_cli(*arguments, stdin=sheet))


def test_cli_reads_files_with_any_line_endings(cli, original_cli, tmp_path):
    for index, content in enumerate((b"a\r\nb: a\r\n", b"a\rb: a\r", b"# c\rb\n", b"a \\\r\nb\r\n")):
        path = tmp_path / f"sheet{index}.sheet"
        path.write_bytes(content)
        for command in ("order", "waves"):
            assert_same(cli(command, str(path)), original_cli(command, str(path)))


def test_cli_missing_file(cli, original_cli):
    got = cli("order", "no-such-file.sheet")
    assert got.returncode == 1
    assert_same(got, original_cli("order", "no-such-file.sheet"))


@pytest.mark.parametrize("arguments", [["waves", "-", "--limit", "x"], ["subset", "-"], ["order"], ["bogus"], []])
def test_cli_usage_errors(cli, arguments):
    assert cli(*arguments, stdin="a\n").returncode == 2
