"""The search syntax described in docs/query-syntax.md.

    laptop refresh          pages containing both terms
    "expense claim"         the words next to each other, in that order
    -contractor             pages without the term
    tag:travel              pages tagged travel
    title:office            pages with the term in their title
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from textproc import term, terms, words

_TOKEN = re.compile(r'"([^"]*)"|(\S+)')
FIELDS = ("tag", "title")


@dataclass
class Query:
    text: str
    highlight: list[str] = field(default_factory=list)  # words as typed, for snippets
    required: list[str] = field(default_factory=list)
    phrases: list[list[str]] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    title_terms: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.required or self.tags or self.title_terms)


def parse(text: str) -> Query:
    query = Query(text=text)
    for match in _TOKEN.finditer(text):
        phrase, token = match.group(1), match.group(2)
        if phrase is not None:
            phrase_terms = terms(phrase)
            if phrase_terms:
                query.phrases.append(phrase_terms)
                _add_unique(query.required, phrase_terms)
                query.highlight.extend(words(phrase))
            continue
        if token.startswith("-") and len(token) > 1:
            _add_unique(query.excluded, terms(token[1:]))
            continue
        name, sep, value = token.partition(":")
        if sep and name.lower() in FIELDS and value:
            if name.lower() == "tag":
                query.tags.append(value.lower())
            else:
                _add_unique(query.title_terms, terms(value))
                query.highlight.extend(words(value))
            continue
        for word in words(token):
            value = term(word)
            if value is not None:
                _add_unique(query.required, [value])
                query.highlight.append(word)
    return query


def _add_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)
