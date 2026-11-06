"""Season rollover and statement preview in the member portal. Owned by the portal team."""

import grainbank.settlement as settlement
from grainbank.settlement import GrainbankError, Ledger, _quantize_bushels, render_statement


def season_banner():
    return f"Current season: {settlement.ACTIVE_SEASON}"


def roll_over(new_season):
    settlement.set_season(new_season)
    return season_banner()


def preview_statement(member, ledger_path):
    try:
        return render_statement(member, Ledger.load(ledger_path))
    except GrainbankError as exc:
        return f"Statement unavailable: {exc}"


def display_bushels(value):
    return f"{_quantize_bushels(value)} bu"
