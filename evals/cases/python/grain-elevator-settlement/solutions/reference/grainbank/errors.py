"""What this package raises on purpose."""


class GrainbankError(Exception):
    """Base class for everything this package raises on purpose."""


class GradingError(GrainbankError):
    """A ticket that cannot be graded, such as an unknown commodity or impossible weights."""


class FeedError(GrainbankError):
    """The board price feed is down, or does not have the price we need."""


class LedgerError(GrainbankError):
    """A posting the ledger refuses."""


class CheckpointError(GrainbankError):
    """A checkpoint file that cannot be used."""
