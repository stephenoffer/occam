"""What the JavaScript and TypeScript rules share: bracket pairs, call arguments, template interpolations, function bodies and where a request's
values go. Each is found in one pass over the code view, where strings and comments are blanked, so hostile input stays linear."""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from typing import NamedTuple

from .brackets import OPENS, pairs  # noqa: F401  pairs is part of this module's interface for the JS rules
from .source import Source

_ARGUMENT_MARK = re.compile(r"[,(\[{`]")
_STATEMENT_MARK = re.compile(r"[;\n(\[{`]")
_CONTINUES = re.compile(r"\s*(?:[.+?:]|&&|\|\||\?\?)")
MAX_STATEMENT = 2000  # what's read of one statement's value
_NOT_A_FUNCTION = {"if", "for", "while", "switch", "catch", "with", "return", "typeof", "await", "new", "else", "do", "try", "finally"}
# A NestJS handler's decorator, with its method.
NEST_ROUTE = re.compile(r"@(Get|Post|Put|Patch|Delete|All)\s*\(")
_RETURN_TYPE = re.compile(r"\s*:\s*[^{};=()]{1,200}")




def argument_spans(code: str, opening: int, brackets: dict[int, int], most: int = 8) -> list[tuple[int, int]]:
    """(start, end) of the first few arguments of the call whose `(` is at `opening`, split at commas outside brackets and templates."""
    close = brackets.get(opening, -1)
    if close < 0:
        return []
    spans: list[tuple[int, int]] = []
    start = position = opening + 1
    while len(spans) < most:
        mark = _ARGUMENT_MARK.search(code, position, close)
        if not mark:
            break
        if mark.group(0) == ",":
            spans.append((start, mark.start()))
            start = position = mark.end()
        elif mark.group(0) == "`":
            end = code.find("`", mark.end(), close)
            if end < 0:
                break
            position = end + 1
        else:
            partner = brackets.get(mark.start(), -1)
            if partner < 0 or partner >= close:
                break
            position = partner + 1
    if len(spans) < most and code[start:close].strip():
        spans.append((start, close))
    return spans


def statement_end(code: str, start: int, brackets: dict[int, int]) -> int:
    """Where the value starting at `start` ends: a `;`, or a line break that nothing carries on, outside brackets and templates."""
    position, limit = start, min(len(code), start + MAX_STATEMENT)
    for _ in range(40):
        mark = _STATEMENT_MARK.search(code, position, limit)
        if not mark:
            return limit
        character = mark.group(0)
        if character == ";":
            return mark.start()
        if character == "\n":
            if code[start:mark.start()].strip() and not _CONTINUES.match(code, mark.end()) and not code[start:mark.start()].rstrip().endswith(("=", "+", "(", ",", "?", ":", "=>", "&&", "||")):
                return mark.start()
            position = mark.end()
        elif character == "`":
            end = code.find("`", mark.end(), limit)
            position = end + 1 if end >= 0 else limit
        else:
            partner = brackets.get(mark.start(), -1)
            if partner < 0:
                return mark.start()
            position = partner + 1
    return position


def with_interpolations(source: Source) -> str:
    """The code view with each template's `${...}` expressions put back, so a value spliced into a template reads as code. The rest of the
    template stays blank, and offsets are unchanged."""
    code, text = source.code, source.text
    pieces: list[str] = []
    position = 0
    while True:
        opening = code.find("`", position)
        if opening < 0:
            break
        closing = code.find("`", opening + 1)
        if closing < 0:
            break
        pieces.append(code[position:opening + 1])
        cursor = opening + 1
        for start, end in interpolations(text, opening + 1, closing):
            pieces.append(code[cursor:start])
            pieces.append(text[start:end])
            cursor = end
        pieces.append(code[cursor:closing])
        position = closing
    pieces.append(code[position:])
    return "".join(pieces)


def interpolations(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """(start, end) of each `${...}` expression's text between `start` and `end` of a template, outermost only."""
    found = []
    position = text.find("${", start, end)
    while position >= 0:
        depth, index = 1, position + 2
        while index < end and depth:
            character = text[index]
            depth += 1 if character == "{" else -1 if character == "}" else 0
            index += 1
        if depth:
            break
        found.append((position + 2, index - 1))
        position = text.find("${", index, end)
    return found


class Function(NamedTuple):
    name: str          # the function's own name, or what it's assigned to, or ""
    parameters: str    # the text between its parentheses
    start: int         # its body's `{`
    end: int           # its body's `}`


def _last_code(code: str, before: int) -> int:
    """The last character before `before` that isn't whitespace, or -1. Each run of whitespace is walked once per brace after it."""
    index = before - 1
    while index >= 0 and code[index] in " \t\r\n":
        index -= 1
    return index


def _parameters_end(code: str, before: int, closers: dict[int, int]) -> int:
    """The `)` that closes a parameter list ending just before `before`, past a TypeScript return type such as `: Promise<void>`, or -1."""
    last = _last_code(code, before)
    if last >= 0 and code[last] == ")" and last in closers:
        return last
    typed = code.rfind(")", max(0, before - 200), before)
    if typed >= 0 and typed in closers and _RETURN_TYPE.fullmatch(code, typed + 1, last + 1):
        return typed
    return -1


def _word_before(code: str, end: int) -> tuple[str, int]:
    """The identifier ending just before `end`, past whitespace, and where it starts. Walked back character by character, so each costs its length."""
    last = _last_code(code, end)
    index = last
    while index >= 0 and (code[index].isalnum() or code[index] in "_$"):
        index -= 1
    return code[index + 1:last + 1], index + 1


def _function_name(code: str, open_parenthesis: int) -> str | None:
    """The name a parameter list belongs to, "" for `function (`, or None when the parenthesis isn't a parameter list, as in `if (`."""
    end = open_parenthesis
    last = _last_code(code, end)
    if last >= 0 and code[last] == ">":  # a generic method, `parse<T>(`
        opening = code.rfind("<", max(0, last - 200), last)
        end = opening if opening >= 0 else end
    name, _ = _word_before(code, end)
    if name in ("function", "async"):
        return ""
    if not name or name in _NOT_A_FUNCTION or name[0].isdigit():
        return None
    return name


def functions(code: str, brackets: dict[int, int]) -> list[Function]:
    """Every function body with a block: declarations, methods, and arrows. A `{` is a body when what comes before it is `=>`, or the `)` of a
    parameter list, possibly with a return type, that follows a name or `function` and isn't `if (...)` or `for (...)`."""
    closers = {close: open_ for open_, close in brackets.items() if code[open_] == "("}
    found = []
    for opening, close in brackets.items():
        if code[opening] != "{":
            continue
        last = _last_code(code, opening)
        if last >= 1 and code[last - 1:last + 1] == "=>":
            found.append(_arrow(code, last - 1, opening, close, closers))
            continue
        parenthesis = _parameters_end(code, opening, closers)
        if parenthesis < 0:
            continue
        name = _function_name(code, closers[parenthesis])
        if name is not None:
            found.append(Function(name, code[closers[parenthesis] + 1:parenthesis], opening, close))
    found.sort(key=lambda function: function.start)
    return found


def _assigned_name(code: str, start: int) -> str:
    """What an arrow function starting at `start` is assigned to: `const run = (`, `run: (`, `this.run = (`, `const run: Handler = (`."""
    word, at = _word_before(code, start)
    if word == "async":
        start = at
    last = _last_code(code, start)
    if last < 0 or code[last] not in "=:" or (code[last] == "=" and last > 0 and code[last - 1] in "=!<>"):
        return ""
    name, at = _word_before(code, last)
    before = _last_code(code, at)
    if code[last] == "=" and before >= 0 and code[before] == ":":  # the word was a type annotation
        name, _ = _word_before(code, before)
    return name


def _arrow(code: str, arrow: int, opening: int, close: int, closers: dict[int, int]) -> Function:
    """An arrow function's parameters, `(a, b) =>` or `a =>`, and the name it's assigned to."""
    parenthesis = _parameters_end(code, arrow, closers)
    if parenthesis >= 0:
        start = closers[parenthesis]
        parameters = code[start + 1:parenthesis]
    else:
        parameters, start = _word_before(code, arrow)
    return Function(_assigned_name(code, start), parameters, opening, close)


def innermost(spans: list[tuple[int, int]], offsets: list[int]) -> dict[int, tuple[int, int]]:
    """For each offset, the innermost of these nested spans that holds it, in one sweep. Spans are bracket pairs, so they nest."""
    ordered = sorted(spans)
    found: dict[int, tuple[int, int]] = {}
    stack: list[tuple[int, int]] = []
    index = 0
    for offset in sorted(set(offsets)):
        while index < len(ordered) and ordered[index][0] < offset:
            span = ordered[index]
            while stack and stack[-1][1] < span[0]:
                stack.pop()
            stack.append(span)
            index += 1
        while stack and stack[-1][1] <= offset:
            stack.pop()
        if stack:
            found[offset] = stack[-1]
    return found


def enclosing_function(bodies: list[Function], offsets: list[int]) -> dict[int, Function]:
    by_span = {(function.start, function.end): function for function in bodies}
    return {offset: by_span[span] for offset, span in innermost(list(by_span), offsets).items()}


def blocks(code: str, brackets: dict[int, int]) -> list[tuple[int, int]]:
    return [(open_, close) for open_, close in brackets.items() if code[open_] == "{"]


def within_budget(bodies: list[Function], length: int, longest: int = 20_000) -> Iterator[Function]:
    """Function bodies to read one by one, until what's been read reaches a few times the file. Nested bodies overlap, so reading each in full
    would be quadratic on deeply nested input; real code nests a few levels and stays well inside this."""
    budget = 8 * length + 200_000
    for function in bodies:
        size = function.end - function.start
        if size > longest:
            continue
        budget -= size
        if budget < 0:
            return
        yield function


def holds_any(offsets: list[int], start: int, end: int) -> bool:
    """Whether a sorted list of offsets has one between start and end."""
    index = bisect.bisect_left(offsets, start)
    return index < len(offsets) and offsets[index] < end
