"""Brackets, function bodies and call arguments for braced languages read without a parser, shared by the Go and JVM rules.

Everything works on a Source's code view, where strings and comments are blanked at the same offsets, so a brace in a string can't
close a body. Bracket partners are found in one pass, which keeps unclosed input linear.
"""

from __future__ import annotations

import bisect
import re
from typing import NamedTuple

from .brackets import OPENS as _OPENS, pairs  # noqa: F401  pairs is part of this module's interface for the Go and JVM rules
from .source import Source

MAX_ARGUMENT = 2000  # what's read of one argument
NOT_A_FUNCTION = {"if", "for", "while", "switch", "catch", "return", "else", "do", "try", "synchronized", "new", "throw", "when", "assert",
                  "super", "this", "case"}




class Body(NamedTuple):
    name: str
    head: int     # where the declaration starts
    start: int    # just past the opening brace
    end: int      # the closing brace
    params: str   # the parameter list, from the code view


# Go: `func (s *Store) Name[T any](params) (results) {`. The parameter list is found by its partner, so it may span lines.
_GO_HEAD = re.compile(r"^func[ \t]+(?:\([^()\n]{0,200}\)[ \t]*)?(\w+)[ \t]*(?:\[[^\]\n]{0,200}\])?\(", re.M)
# Java: modifiers and annotations, a return type, then a name and its parameters. Kotlin: `fun name(`.
_JAVA_HEAD = re.compile(r"^[ \t]*(?:@[\w.]+(?:\([^()\n]{0,200}\))?[ \t]+){0,4}(?:(?:public|private|protected|static|final|abstract|synchronized|default|native|strictfp)[ \t]+){0,6}"
                        r"(?:<[^<>\n]{0,100}>[ \t]+)?([\w$.]{1,150}(?:<[^\n{};=()]{0,200}>)?(?:\[\])*)[ \t]+(\w+)[ \t]*\(", re.M)
_KOTLIN_HEAD = re.compile(r"^[ \t]*(?:[\w@]+[ \t]+){0,6}fun[ \t]+(?:<[^<>\n]{0,100}>[ \t]*)?(?:[\w.]+\.)?(\w+)[ \t]*\(", re.M)
_AFTER_JAVA_PARAMS = re.compile(r"\s*(?:throws\s+[\w.,\s]{1,300}?)?\{")
_AFTER_KOTLIN_PARAMS = re.compile(r"\s*(?::\s*[^{=\n]{1,200}?)?\{")


def _go_body_opening(code: str, position: int, pairs_map: dict[int, int]) -> int:
    """The brace that opens a Go function's body, after its results: `(int, error) {`, `map[string]interface{} {`. Go puts it on the
    signature's last line, and a result list or an `interface{}` in a type is stepped over."""
    limit = min(len(code), position + 300)
    while position < limit:
        character = code[position]
        if character == "{":
            if re.search(r"(?:interface|struct)\s*$", code[max(0, position - 12):position]):
                position = pairs_map.get(position, limit) + 1
                continue
            return position
        if character in "([":
            position = pairs_map.get(position, limit) + 1
            continue
        if character in ";}\n=":
            return -1
        position += 1
    return -1


def functions(source: Source, pairs_map: dict[int, int]) -> list[Body]:
    """Every outermost function or method with a body, in order, so they don't overlap. Go can't nest declarations and Java nests only
    local and anonymous classes, whose code then counts as the enclosing method's. Keeping them apart would copy nested text once per
    level, which hostile input can make quadratic."""
    code = source.code
    found: list[Body] = []
    if source.language == "go":
        heads = ((match.group(1), match.start(), match.end() - 1) for match in _GO_HEAD.finditer(code))
        after = None
    elif source.language == "kotlin":
        heads = ((match.group(1), match.start(), match.end() - 1) for match in _KOTLIN_HEAD.finditer(code))
        after = _AFTER_KOTLIN_PARAMS
    else:
        heads = ((match.group(2), match.start(), match.end() - 1) for match in _JAVA_HEAD.finditer(code)
                 if match.group(1) not in NOT_A_FUNCTION and not match.group(1).endswith(("new", "return", "throw")))
        after = _AFTER_JAVA_PARAMS
    reached = -1
    for name, head, opening in heads:
        if name in NOT_A_FUNCTION or head < reached:
            continue
        closing = pairs_map.get(opening, -1)
        if closing < 0:
            continue
        if after is None:
            brace = _go_body_opening(code, closing + 1, pairs_map)
        else:
            match = after.match(code, closing + 1)
            brace = match.end() - 1 if match else -1
        end = pairs_map.get(brace, -1) if brace > 0 else -1
        if end > 0:
            found.append(Body(name, head, brace + 1, end, code[opening + 1:closing]))
            reached = end
    return found


def enclosing(bodies: list[Body], offset: int, starts: list[int] | None = None) -> Body | None:
    """The function holding this offset. `bodies` is functions()'s list, sorted and disjoint; pass `starts`, their start offsets,
    when calling this in a loop."""
    at = bisect.bisect_right(starts if starts is not None else [body.start for body in bodies], offset) - 1
    return bodies[at] if at >= 0 and offset <= bodies[at].end else None


class Budget:
    """Work a file may cost beyond one pass, counted in characters read. A check that runs out stops with what it found, so hostile
    input can't make a lookback per call quadratic."""

    def __init__(self, text: str) -> None:
        self.left = 8 * len(text) + 200_000

    def spend(self, amount: int) -> bool:
        self.left -= max(amount, 1)
        return self.left > 0


def arguments(code: str, opening: int, pairs_map: dict[int, int]) -> list[tuple[int, int]]:
    """(start, end) of each top-level argument of the call whose parenthesis opens at `opening`. Each bracket jumps to its partner,
    so a call costs a few steps however much it holds."""
    closing = pairs_map.get(opening, -1)
    if closing < 0:
        return []
    spans: list[tuple[int, int]] = []
    cursor = position = opening + 1
    while position < closing:
        character = code[position]
        if character == ",":
            spans.append((cursor, position))
            cursor = position + 1
        elif character in _OPENS:
            partner = pairs_map.get(position, -1)
            if partner < 0 or partner > closing:
                break
            position = partner
        position += 1
    if code[cursor:closing].strip():
        spans.append((cursor, closing))
    return [(start, min(end, start + MAX_ARGUMENT)) for start, end in spans]


def strip(code: str, span: tuple[int, int]) -> tuple[int, int]:
    """The span without surrounding whitespace."""
    start, end = span
    while start < end and code[start].isspace():
        start += 1
    while end > start and code[end - 1].isspace():
        end -= 1
    return start, end


def one_per_line(found: list[tuple]) -> list[tuple]:
    """The first finding of each rule on each line. A line repeating a sink thousands of times says it once."""
    seen: set[tuple[str, int]] = set()
    kept = []
    for finding in found:
        if (finding[0], finding[1]) not in seen:
            seen.add((finding[0], finding[1]))
            kept.append(finding)
    return kept


def literal_text(text: str, start: int, end: int, strings: re.Pattern) -> str:
    """The written-out text of the string literals in [start, end), joined, for the language's `strings` pattern."""
    return " ".join(match.group(0)[1:-1] for match in strings.finditer(text, start, end))


def parts(code: str, start: int, end: int, separator: str) -> list[tuple[int, int]]:
    """(start, end) of each part of the expression at [start, end) split on `separator` outside brackets, as the operands of a `+`
    chain or the arguments of an `append`. Strings are blanked in the code view, so a separator inside one doesn't count."""
    found, depth, cursor = [], 0, start
    for index in range(start, end):
        character = code[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == separator and depth == 0:
            found.append(strip(code, (cursor, index)))
            cursor = index + 1
    found.append(strip(code, (cursor, end)))
    return [(a, b) for a, b in found if b > a]


_NAME_PART = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_SECRET_WORDS = {"secret", "token", "password", "passwd", "pwd", "passcode", "passphrase", "nonce", "otp", "salt", "csrf", "xsrf", "code", "pin",
                 "apikey", "sessionid", "credential", "credentials"}
_SECRET_PAIRS = {("api", "key"), ("access", "key"), ("secret", "key"), ("signing", "key"), ("private", "key"), ("session", "id"), ("session", "key")}


def secret_named(name: str) -> bool:
    """Whether a name says it holds something that grants access, by its whole words: `resetToken`, `invite_code` and `apiKey` do, while
    `pingInterval`, `sleeping` and `spinWait` don't."""
    words = [word.lower() for word in _NAME_PART.findall(name)]
    return any(word in _SECRET_WORDS for word in words) or any(pair in _SECRET_PAIRS for pair in zip(words, words[1:]))
