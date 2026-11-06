from decimal import Decimal
from pathlib import Path

import pytest

from freightquote import Lane, Mode, ModeRates, Shipment, load_rate_card

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def card():
    return load_rate_card(DATA / "ratecard.json")


@pytest.fixture
def fuel_index():
    return DATA / "fuel_index.json"


@pytest.fixture
def road_lane():
    return Lane("R1", "Halifax", "Montreal", Mode.ROAD, 1000, Decimal("18000"), Decimal("80"), True)


@pytest.fixture
def rail_lane():
    return Lane("T1", "Montreal", "Winnipeg", Mode.RAIL, 2000, Decimal("60000"), Decimal("120"))


@pytest.fixture
def air_lane():
    return Lane("A1", "Vancouver", "Whitehorse", Mode.AIR, 1500, Decimal("4000"), Decimal("22"))


@pytest.fixture
def road_rates():
    return ModeRates(Decimal("0.40"), Decimal("0.20"), Decimal("85.00"))


@pytest.fixture
def pallet():
    return Shipment("S-100", Decimal("600"), Decimal("1.2"), 4)
