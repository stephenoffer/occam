from datetime import date
from decimal import Decimal

from tidewater.domain.claims.assess import Claim, ClaimAssessor


def test_payout_uses_the_rate_it_was_given():
    assessor = ClaimAssessor("EUR", rate_lookup=lambda base, quote, as_of: Decimal("2"))
    assert assessor.payout(Claim("CL-1", Decimal("100"), "USD", Decimal("0")), date(2026, 10, 20)) == Decimal("200.00")


def test_deductible_comes_off_first():
    assessor = ClaimAssessor("EUR", rate_lookup=lambda base, quote, as_of: Decimal("1"))
    assert assessor.payout(Claim("CL-2", Decimal("100"), "USD", Decimal("25")), date(2026, 10, 20)) == Decimal("75.00")
