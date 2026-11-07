import json
from datetime import date

import pytest

from helpers import CATALOG, basket, write_settings
from till import journal
from till.ring import RingError, ring


def test_ring_writes_the_journal_and_returns_a_receipt(tmp_path):
    write_settings(tmp_path)
    rung = ring(tmp_path, basket("2026-11-09T09:14:03", [{"sku": "PNT-1L-WHT", "qty": 2}, {"sku": "PNT-BRUSH-2IN"}],
                                 [{"type": "cash", "pence": 3000}]), CATALOG)
    assert rung.record.sale == "BRH01-1-261109-0001"
    assert rung.record.change_pence == 3
    assert journal.read_day(tmp_path, date(2026, 11, 9)) == [rung.record]
    assert "CHANGE" in rung.receipt


def test_a_refused_sale_writes_nothing(tmp_path):
    write_settings(tmp_path)
    with pytest.raises(RingError, match="still to pay"):
        ring(tmp_path, basket("2026-11-09T10:00:00", [{"sku": "TLS-SAW-22IN"}], [{"type": "cash", "pence": 1000}]), CATALOG)
    assert not (tmp_path / "journal").exists()


def test_sample_baskets_ring(tmp_path):
    write_settings(tmp_path)
    samples = sorted((__import__("pathlib").Path(__file__).parents[1] / "data" / "baskets").glob("*.json"))
    assert samples
    for path in samples:
        ring(tmp_path, json.loads(path.read_text()), CATALOG)
    assert len(journal.read_day(tmp_path, date(2026, 11, 9))) == len(samples)
