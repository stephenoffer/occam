"""Word families, so `gate` can tell that a new name probably repeats one that already exists."""

from __future__ import annotations

import re

SYNONYMS = [
    {"get", "fetch", "retrieve", "load", "read", "find", "lookup", "query", "pull"},
    {"create", "make", "build", "generate", "new", "construct"},
    {"delete", "remove", "destroy", "drop", "purge", "clear"},
    {"update", "modify", "change", "patch", "edit", "set"},
    {"validate", "verify", "check", "ensure", "assert", "sanitize"},
    {"parse", "decode", "deserialize", "unmarshal", "extract"},
    {"format", "render", "serialize", "encode", "marshal", "stringify", "dump"},
    {"compute", "calculate", "calc", "sum", "total"},
    {"send", "dispatch", "emit", "publish", "post", "notify"},
    {"retry", "backoff", "attempt"}, {"cache", "memoize", "memo", "lru"}, {"date", "datetime", "time", "timestamp"},
    {"user", "account", "customer", "member"}, {"auth", "login", "authenticate", "token", "session"},
    {"money", "price", "amount", "currency", "invoice"}, {"email", "mail"}, {"http", "request", "client", "api"},
    {"config", "settings", "conf", "options"}, {"log", "logger", "logging"}, {"csv", "tsv"}, {"json", "yaml", "toml"},
]
_FILLER = {"with", "for", "the", "and", "from", "into", "that", "this", "using", "use", "of", "to", "in", "on", "by", "an", "or", "it", "is", "at", "as"}


def _words(text: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [w.lower() for w in re.findall(r"[A-Za-z][a-z0-9]*|[A-Z]+", spaced) if len(w) >= 2 and w.lower() not in _FILLER]


def _expand(words: list[str]) -> dict[str, float]:
    expanded = {word: 1.0 for word in words}
    for family in SYNONYMS:
        if family & set(words):
            for member in family:
                expanded.setdefault(member, 0.6)
    return expanded


def _symbols(project) -> list[tuple[str, str, int, str, str]]:
    found = []
    for path, facts in project.facts.items():
        for definition in (facts or {}).get("defs", []):
            if not definition["name"].startswith("__"):
                found.append((definition["name"], path, definition["line"], definition["kind"], definition.get("class") or ""))
        for item in (facts or {}).get("classes", []):
            found.append((item["name"], path, item["line"], "class", ""))
    return found
