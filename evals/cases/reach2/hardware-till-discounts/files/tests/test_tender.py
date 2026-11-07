import pytest

from till.tender import Tender, TenderError, parse_tenders, settle


def test_cash_gives_change():
    assert settle(3246, [Tender("cash", 3500)]) == 254


def test_card_then_cash():
    assert settle(3398, [Tender("card", 2000), Tender("cash", 2000)]) == 602


def test_exact_card():
    assert settle(2447, [Tender("card", 2447)]) == 0


def test_card_over_the_amount_due_is_refused():
    with pytest.raises(TenderError, match="card"):
        settle(1000, [Tender("card", 1200)])


def test_short_payment():
    with pytest.raises(TenderError, match="still to pay"):
        settle(1000, [Tender("cash", 900)])


@pytest.mark.parametrize("entries", [[], [{"type": "cheque", "pence": 100}], [{"type": "cash", "pence": -5}],
                                     [{"type": "cash", "pence": "100"}]])
def test_parse_rejects(entries):
    with pytest.raises(TenderError):
        parse_tenders(entries)
