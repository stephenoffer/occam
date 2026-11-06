"""The wall clock, in one place so that it can be stubbed."""

from datetime import date


def today() -> date:
    return date.today()
