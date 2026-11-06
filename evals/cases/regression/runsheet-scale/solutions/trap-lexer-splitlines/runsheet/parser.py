"""Read run sheet text into Step records."""

import re

from .model import ParseError, Step

TOKEN = re.compile(
    r"""
    (?P<space>[ \t]+)
  | (?P<joined>\\\r?\n)
  | (?P<comment>\#[^\n]*)
  | (?P<newline>\r?\n)
  | (?P<quoted>"(?:[^"\\\n]|\\.)*")
  | (?P<colon>:)
  | (?P<tilde>~)
  | (?P<caret>\^)
  | (?P<word>[^\s:~^#"\\]+)
    """,
    re.VERBOSE,
)
NAME_KINDS = ("word", "quoted")


def _line_tokens(raw, line):
    position = 0
    while position < len(raw):
        match = TOKEN.match(raw, position)
        if match is None:
            raise ParseError(line, f"unexpected {raw[position]!r}")
        kind = match.lastgroup
        value = match.group()
        position = match.end()
        if kind == "quoted":
            yield kind, re.sub(r"\\(.)", r"\1", value[1:-1]), line
        elif kind != "space" and kind != "comment":
            yield kind, value, line


def _tokens(text):
    lines = text.splitlines()
    for number, raw in enumerate(lines, start=1):
        joined = raw.endswith("\\") and not TOKEN.fullmatch(raw) and number < len(lines)
        yield from _line_tokens(raw[:-1] if joined else raw, number)
        if not joined:
            yield "newline", "\n", number


def _take_name(tokens, index, after_what, line):
    if index >= len(tokens) or tokens[index][0] not in NAME_KINDS:
        raise ParseError(line, f"expected a value after {after_what!r}")
    return tokens[index][1]


def _build_step(tokens):
    kind, name, line = tokens[0]
    if kind not in NAME_KINDS:
        raise ParseError(line, f"expected a step name, got {name!r}")
    needs, after, priority = [], [], 0
    seen_colon = False
    index = 1
    while index < len(tokens):
        kind, value, line = tokens[index]
        index += 1
        if kind == "colon":
            if seen_colon:
                raise ParseError(line, "unexpected ':'")
            seen_colon = True
        elif kind == "tilde":
            after.append(_take_name(tokens, index, "~", line))
            index += 1
        elif kind == "caret":
            digits = _take_name(tokens, index, "^", line)
            index += 1
            try:
                priority = int(digits)
            except ValueError:
                raise ParseError(line, f"bad priority {digits!r}") from None
        elif seen_colon:
            needs.append(value)
        else:
            raise ParseError(line, f"expected ':' before {value!r}")
    return Step(name, tuple(needs), tuple(after), priority)


def parse(text):
    steps = []
    current = []
    for token in _tokens(text):
        if token[0] != "newline":
            current.append(token)
        elif current:
            steps.append(_build_step(current))
            current = []
    if current:
        steps.append(_build_step(current))
    return steps
