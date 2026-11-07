from datetime import date

import pytest

from helpers import CATALOG, basket, write_settings
from till.endofday import AlreadyClosed, close_day
from till.journal import journal_path
from till.ring import ring

DAY = date(2026, 11, 9)


def test_close_copies_the_journal_to_the_outbox(tmp_path):
    write_settings(tmp_path, store="BRH03")
    ring(tmp_path, basket("2026-11-09T09:00:00", [{"sku": "PLB-PTFE"}], [{"type": "cash", "pence": 100}]), CATALOG)
    path = close_day(tmp_path, DAY)
    assert path == tmp_path / "outbox" / "BRH03-2026-11-09.tape"
    assert path.read_bytes() == journal_path(tmp_path, DAY).read_bytes()


def test_a_day_with_no_sales_still_closes(tmp_path):
    write_settings(tmp_path)
    assert close_day(tmp_path, DAY).read_text() == ""


def test_closing_twice_is_refused(tmp_path):
    write_settings(tmp_path)
    close_day(tmp_path, DAY)
    with pytest.raises(AlreadyClosed):
        close_day(tmp_path, DAY)


def test_already_sent_counts_as_closed(tmp_path):
    write_settings(tmp_path)
    sent = tmp_path / "outbox" / "sent" / "BRH01-2026-11-09.tape"
    sent.parent.mkdir(parents=True)
    sent.write_text("")
    with pytest.raises(AlreadyClosed):
        close_day(tmp_path, DAY)
