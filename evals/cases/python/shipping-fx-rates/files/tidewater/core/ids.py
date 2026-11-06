"""Check digits for the identifiers we issue."""


def check_digit(body: str) -> int:
    total = sum((index + 1) * (ord(ch) % 11) for index, ch in enumerate(body))
    return total % 10


def with_check_digit(body: str) -> str:
    return f"{body}{check_digit(body)}"


def is_valid(identifier: str) -> bool:
    return len(identifier) > 1 and identifier[-1].isdigit() and check_digit(identifier[:-1]) == int(identifier[-1])
