import pytest

from findoc import config


def test_defaults_without_a_file(tmp_path):
    assert config.load(tmp_path) == config.Settings()


def test_values_are_read(tmp_path):
    (tmp_path / ".findocrc").write_text("[search]\nlimit = 3\nsnippet_width = 120\n")
    assert config.load(tmp_path) == config.Settings(limit=3, snippet_width=120)


def test_bad_values_stop_with_a_message(tmp_path):
    (tmp_path / ".findocrc").write_text("[search]\nlimit = many\n")
    with pytest.raises(SystemExit, match="whole number"):
        config.load(tmp_path)
