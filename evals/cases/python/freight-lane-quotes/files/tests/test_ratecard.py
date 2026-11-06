from dataclasses import replace
from decimal import Decimal

import pytest

from freightquote import Mode, RateCardError, load_rate_card
from freightquote.ratecard import validate_rate_card


def test_published_card_loads(card):
    assert card.version == "2026-Q4"
    assert set(card.rates) == set(Mode)
    assert card.lane("HFX-MTL-ROAD").distance_km == 1250


def test_published_card_validates(card):
    assert validate_rate_card(card) is True


def test_unknown_lane_is_named(card):
    with pytest.raises(RateCardError, match="NOPE"):
        card.lane("NOPE")


def test_missing_file_raises(tmp_path):
    with pytest.raises(RateCardError, match="cannot load"):
        load_rate_card(tmp_path / "missing.json")


def test_bad_json_raises(tmp_path):
    path = tmp_path / "card.json"
    path.write_text("{not json")
    with pytest.raises(RateCardError, match="cannot load"):
        load_rate_card(path)


def test_negative_rate_is_rejected(card):
    rates = dict(card.rates)
    rates[Mode.ROAD] = replace(rates[Mode.ROAD], per_km=Decimal("-1"))
    with pytest.raises(RateCardError, match="non-positive road"):
        validate_rate_card(replace(card, rates=rates))


def test_missing_mode_is_rejected(card):
    rates = {mode: value for mode, value in card.rates.items() if mode is not Mode.AIR}
    with pytest.raises(RateCardError, match="no rates for air"):
        validate_rate_card(replace(card, rates=rates))
