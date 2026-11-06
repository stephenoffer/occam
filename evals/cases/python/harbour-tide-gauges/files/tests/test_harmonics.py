import pytest

from tidekit import Constituent, predict_level_m, principal_constituent

M2 = Constituent("M2", 28.984, 1.2, 0.0)
S2 = Constituent("S2", 30.0, 0.3, 90.0)


def test_prediction_sums_constituents():
    assert predict_level_m([M2, S2], 0.0, 1.0) == pytest.approx(2.2)


def test_prediction_is_periodic():
    period_h = 360.0 / M2.speed_deg_per_h
    assert predict_level_m([M2], period_h) == pytest.approx(predict_level_m([M2], 0.0))


def test_principal_is_largest_amplitude():
    assert principal_constituent([S2, M2]) is M2
