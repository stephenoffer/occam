"""One pass over a file's code that pairs each opening bracket with its closing one, for the rules of every brace language that read a
call's arguments or a block's body. Each rule then looks a pair up instead of walking the text, so no input makes that quadratic."""

from __future__ import annotations

import re

_BRACKET = re.compile(r"[()\[\]{}]")
OPENS = {"(": ")", "[": "]", "{": "}"}


def pairs(code: str) -> dict[int, int]:
    """Opening offset to closing offset, in one pass, so an unclosed bracket costs a lookup and not a walk to the end of the file. Strings
    and comments are already blanked in `code`. A closer that doesn't match the innermost opener is ignored, so a stray one can't shift
    the rest. Unclosed openers are absent."""
    found: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    for match in _BRACKET.finditer(code):
        character, index = match.group(0), match.start()
        if character in OPENS:
            stack.append((character, index))
        elif stack and OPENS[stack[-1][0]] == character:
            found[stack.pop()[1]] = index
    return found


def inside(text: str, paired: dict[int, int], opening: int, limit: int = 2000) -> str:
    """What's between the bracket at `opening` and its pair, or the next `limit` characters if it's unclosed or further."""
    closing = paired.get(opening, -1)
    end = closing if opening < closing <= opening + limit else min(len(text), opening + 1 + limit)
    return text[opening + 1:end]
