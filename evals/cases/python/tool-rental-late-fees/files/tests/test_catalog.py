import pytest

from toolhire.catalog import CATALOG, in_class, lookup


def test_lookup():
    assert lookup("ORBITAL").tool_class == "small"


def test_lookup_unknown():
    with pytest.raises(KeyError):
        lookup("FLUX-CAPACITOR")


def test_in_class_is_sorted():
    assert [tool.sku for tool in in_class("heavy")] == ["MINI-DIGGER", "TOWER"]


def test_every_tool_has_a_deposit():
    assert all(tool.deposit_cents > 0 for tool in CATALOG.values())
