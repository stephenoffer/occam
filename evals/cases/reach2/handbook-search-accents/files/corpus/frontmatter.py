"""Front matter: optional `key: value` lines between `---` fences at the top of a page.

Only flat string values are supported. Lists are written either as `[a, b]` or
as `a, b`. Anything that doesn't parse is left in the body, so a page with a
broken header still shows up in search.
"""

from __future__ import annotations

FENCE = "---"


def split(text: str) -> tuple[dict[str, str], str]:
    """Return (fields, body). Pages without front matter have no fields."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FENCE:
        return {}, text
    fields: dict[str, str] = {}
    for number, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if stripped == FENCE:
            return fields, "".join(lines[number + 1:])
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(":")
        if not sep or not key.strip():
            return {}, text
        fields[key.strip().lower()] = _unquote(value.strip())
    return {}, text


def parse_list(value: str) -> tuple[str, ...]:
    """'[a, b]' or 'a, b' -> ('a', 'b'); blank entries are dropped."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return tuple(_unquote(item.strip()) for item in value.split(",") if item.strip())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value
