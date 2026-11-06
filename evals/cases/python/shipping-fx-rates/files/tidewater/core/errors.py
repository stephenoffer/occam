"""Errors the command line reports cleanly."""


class TidewaterError(Exception):
    pass


class RateUnavailable(TidewaterError, LookupError):
    """No exchange rate can be given for the request."""


class DocumentError(TidewaterError, ValueError):
    """A document is missing a field or has a malformed one."""
