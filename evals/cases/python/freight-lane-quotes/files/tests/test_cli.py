from pathlib import Path

import pytest

import freightquote.__main__ as cli

DATA = Path(__file__).resolve().parents[1] / "data"
BASE_ARGS = [
    "--card", str(DATA / "ratecard.json"),
    "--fuel", str(DATA / "fuel_index.json"),
    "--weight", "120",
    "--volume", "1.2",
]  # fmt: skip


def test_quote_prints_a_total(capsys):
    assert cli.main([*BASE_ARGS, "--lane", "HFX-MTL-ROAD"]) == 0
    assert "total" in capsys.readouterr().out


def test_unknown_lane_exits_2(capsys):
    assert cli.main([*BASE_ARGS, "--lane", "NOPE"]) == 2
    assert "NOPE" in capsys.readouterr().err


def test_unexpected_failure_exits_3(monkeypatch):
    def explode(args):
        raise RuntimeError("bug")

    monkeypatch.setattr(cli, "_run", explode)
    assert cli.main([*BASE_ARGS, "--lane", "HFX-MTL-ROAD"]) == 3


def test_lane_is_required():
    with pytest.raises(SystemExit):
        cli.main(BASE_ARGS)
