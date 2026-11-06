"""Assessing what a claim pays out."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from tidewater.core.fx import spot_rate
from tidewater.core.money import percent_of, round_cents

RateLookup = Callable[[str, str], Decimal]


@dataclass(frozen=True)
class Claim:
    claim_id: str
    amount: Decimal
    currency: str
    deductible_percent: Decimal


class ClaimAssessor:
    def __init__(self, settlement_currency: str, rate_lookup: RateLookup = spot_rate) -> None:
        self._settlement_currency = settlement_currency
        self._rate_lookup = rate_lookup

    def payout(self, claim: Claim) -> Decimal:
        covered = claim.amount - percent_of(claim.amount, claim.deductible_percent)
        return round_cents(covered * self._rate_lookup(claim.currency, self._settlement_currency))
