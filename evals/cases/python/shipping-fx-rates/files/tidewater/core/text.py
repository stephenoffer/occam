"""Text helpers for the fixed-width and report formats."""


def pad(value: str, width: int) -> str:
    if len(value) > width:
        raise ValueError(f"{value!r} doesn't fit in {width} characters")
    return value.ljust(width)


def truncate(value: str, width: int) -> str:
    return value if len(value) <= width else value[: max(width - 1, 0)] + "~"
