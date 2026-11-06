from decimal import Decimal

import pytest

from tidewater.core.errors import DocumentError
from tidewater.domain.rating.fuel import fuel_surcharge
from tidewater.domain.rating.pricing import price_freight
from tidewater.domain.rating.tariff import base_freight_usd


def test_base_freight():
    assert base_freight_usd("YOK-SIN", Decimal("10")) == Decimal("743.00")


def test_unknown_lane():
    with pytest.raises(DocumentError):
        base_freight_usd("MOON-MARS", Decimal("1"))


def test_fuel_surcharge_in_usd():
    assert fuel_surcharge(Decimal("1000"), "USD") == Decimal("85.00")


def test_price_freight_in_usd():
    price = price_freight("SIN-RTM", Decimal("10"), "USD")
    assert price.freight == Decimal("1825.00")
    assert price.fuel == Decimal("155.13")


def test_price_freight_in_eur():
    assert price_freight("SIN-RTM", Decimal("10"), "EUR").freight == Decimal("1642.50")
