"""Records and errors shared across the package."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    name: str
    needs: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    priority: int = 0

    def __post_init__(self):
        object.__setattr__(self, "needs", tuple(self.needs))
        object.__setattr__(self, "after", tuple(self.after))


class PlanError(Exception):
    """Base class for everything that can be wrong with a run sheet."""


class ParseError(PlanError):
    def __init__(self, line, problem):
        self.line = line
        super().__init__(f"line {line}: {problem}")


class UnknownStepError(PlanError):
    def __init__(self, missing, needed_by=None):
        self.missing = missing
        self.needed_by = needed_by
        suffix = f" (needed by {needed_by!r})" if needed_by is not None else ""
        super().__init__(f"unknown step {missing!r}{suffix}")


class CycleError(PlanError):
    def __init__(self, blocked, cycle):
        self.blocked = blocked
        self.cycle = cycle
        reason = "cycle: " + " -> ".join(cycle) if cycle else "nothing can run"
        super().__init__(f"{reason} ({len(blocked)} blocked)")
