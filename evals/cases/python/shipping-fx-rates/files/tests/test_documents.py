import json
import subprocess
import sys
from decimal import Decimal

import pytest

from tidewater.core.errors import DocumentError
from tidewater.services.claims_desk import assess_claim
from tidewater.services.closing import close_period
from tidewater.services.filing import file_declaration
from tidewater.services.invoicing import invoice
from tidewater.services.quoting import quote
from tidewater.services.settlements import settle


def test_quote_total():
    result = quote({"lane": "SIN-RTM", "tonnes": "10", "currency": "USD", "booked_on": "2026-10-20"})
    assert Decimal(result["total"]) == Decimal("1825.00") + Decimal("155.13") + Decimal("45.00") + Decimal("25.00") + Decimal("49.50")


def test_quote_lists_its_adjustments():
    result = quote({"lane": "YOK-SIN", "tonnes": "4", "currency": "USD", "booked_on": "2026-10-20"})
    assert set(result["adjustments"]) == {"SEC", "DOC", "CNL"}


def test_quote_needs_a_booking_date():
    with pytest.raises(DocumentError):
        quote({"lane": "SIN-RTM", "tonnes": "10", "currency": "USD"})


def test_invoice_converts_its_lines():
    result = invoice({"invoice_id": "I-1", "lane": "YOK-SIN", "currency": "USD", "issued_on": "2026-10-22", "due_on": "2026-11-21",
                      "lines": [{"description": "Freight", "amount": "900", "currency": "EUR"}]})
    assert result["adjustments"]["SEC"] == "45.00"
    assert result["total"] == str(Decimal("1000.00") + Decimal("45.00") + Decimal("25.00") + Decimal("202.71"))


def test_settlement_total():
    result = settle({"carrier": "C-1", "currency": "USD", "settled_on": "2026-10-25",
                     "payables": [{"reference": "P-1", "amount": "900", "currency": "EUR"},
                                  {"reference": "P-2", "amount": "100", "currency": "USD"}]})
    assert result["total"] == "1100.00"


def test_declaration_duty():
    result = file_declaration({"declaration_id": "D-1", "importing_currency": "USD", "filed_on": "2026-10-25",
                               "items": [{"hs_code": "6204", "value": "1000", "currency": "USD"},
                                         {"hs_code": "8517", "value": "5000", "currency": "USD"}]})
    assert result == {"kind": "declaration", "currency": "USD", "items": 2, "total": "120.00"}


def test_claim_payout():
    result = assess_claim({"claim_id": "CL-1", "amount": "1000", "currency": "USD", "deductible_percent": "10",
                           "settlement_currency": "USD", "assessed_on": "2026-10-25", "incident_on": "2026-08-01"})
    assert result["total"] == "900.00"


def test_closing_revaluation():
    result = close_period({"reporting_currency": "USD", "period_end": "2026-10-31",
                           "balances": [{"amount": "900", "currency": "EUR"}, {"amount": "50", "currency": "USD"}]})
    assert result["total"] == "1050.00"


def test_cli_quote(tmp_path):
    path = tmp_path / "quote.json"
    path.write_text(json.dumps({"lane": "SIN-RTM", "tonnes": "10", "currency": "USD", "booked_on": "2026-10-20"}))
    done = subprocess.run([sys.executable, "-m", "tidewater", "quote", str(path)], capture_output=True, text=True, check=True)
    assert json.loads(done.stdout)["kind"] == "quote"


def test_cli_batch(tmp_path):
    path = tmp_path / "batch.json"
    doc = {"carrier": "C-1", "currency": "USD", "settled_on": "2026-10-25",
           "payables": [{"reference": "P-1", "amount": "100", "currency": "USD"}]}
    path.write_text(json.dumps([{"kind": "settlement", "doc": doc}, {"kind": "settlement", "doc": doc}]))
    done = subprocess.run([sys.executable, "-m", "tidewater", "batch", str(path)], capture_output=True, text=True, check=True)
    assert [row["total"] for row in json.loads(done.stdout)] == ["100.00", "100.00"]


def test_cli_reports_a_bad_document(tmp_path):
    path = tmp_path / "quote.json"
    path.write_text(json.dumps({"lane": "SIN-RTM", "currency": "USD"}))
    done = subprocess.run([sys.executable, "-m", "tidewater", "quote", str(path)], capture_output=True, text=True)
    assert done.returncode == 2
    assert "error:" in done.stderr
