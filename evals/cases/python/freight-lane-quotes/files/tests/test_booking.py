from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from freightquote import BookingFailed, Quote, QuoteLine, submit_booking

NOW = datetime(2026, 11, 5, tzinfo=UTC)


@pytest.fixture
def quote():
    lines = (QuoteLine("base freight", Decimal("100.00")),)
    return Quote("S-1", "R1", lines, Decimal("100.00"), NOW, NOW)


def test_returns_the_carrier_reference(quote):
    client = Mock()
    client.submit.return_value = {"reference": "CR-77"}
    receipt = submit_booking(client, quote, sleep=Mock())
    assert receipt.carrier_reference == "CR-77"
    client.submit.assert_called_once_with({"shipment": "S-1", "lane": "R1", "total": "100.00"})


def test_retries_a_transient_failure(quote):
    client = Mock()
    client.submit.side_effect = [ConnectionError("reset"), {"reference": "CR-78"}]
    sleep = Mock()
    assert submit_booking(client, quote, sleep=sleep).carrier_reference == "CR-78"
    sleep.assert_called_once_with(2.0)


def test_gives_up_after_the_last_attempt(quote):
    client = Mock()
    client.submit.side_effect = TimeoutError("slow")
    with pytest.raises(BookingFailed, match="after 3 tries"):
        submit_booking(client, quote, sleep=Mock())
    assert client.submit.call_count == 3


def test_response_without_reference_is_a_failure(quote):
    client = Mock()
    client.submit.return_value = {"status": "queued"}
    with pytest.raises(BookingFailed, match="no reference"):
        submit_booking(client, quote, sleep=Mock())


def test_other_errors_are_not_retried(quote):
    client = Mock()
    client.submit.side_effect = PermissionError("revoked")
    with pytest.raises(PermissionError):
        submit_booking(client, quote, sleep=Mock())
    assert client.submit.call_count == 1
