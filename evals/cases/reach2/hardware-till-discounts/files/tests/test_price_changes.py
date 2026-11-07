from datetime import date

import pytest

from catalog.price_changes import apply_price_changes, read_price_changes
from catalog.products import load_catalog


def write(tmp_path, body):
    path = tmp_path / "changes.csv"
    path.write_text("sku,new_price_pence,effective\n" + body)
    return path


def test_applies_changes_due_by_the_date(tmp_path):
    changes = read_price_changes(write(tmp_path, "PNT-1L-WHT,1349,2026-11-01\nTLS-TAPE-5M,849,2026-12-01\n"))
    updated, missing = apply_price_changes(load_catalog(), changes, date(2026, 11, 9))
    assert updated.get("PNT-1L-WHT").price_pence == 1349
    assert updated.get("TLS-TAPE-5M").price_pence == 799
    assert missing == []


def test_later_change_wins(tmp_path):
    changes = read_price_changes(write(tmp_path, "PLB-PTFE,129,2026-11-05\nPLB-PTFE,109,2026-11-01\n"))
    updated, _ = apply_price_changes(load_catalog(), changes, date(2026, 11, 9))
    assert updated.get("PLB-PTFE").price_pence == 129


def test_unknown_skus_are_reported_not_added(tmp_path):
    changes = read_price_changes(write(tmp_path, "NEW-THING,500,2026-11-01\n"))
    updated, missing = apply_price_changes(load_catalog(), changes, date(2026, 11, 9))
    assert missing == ["NEW-THING"] and "NEW-THING" not in updated


def test_rejects_bad_prices(tmp_path):
    with pytest.raises(ValueError, match="line 2"):
        read_price_changes(write(tmp_path, "PLB-PTFE,0,2026-11-01\n"))
