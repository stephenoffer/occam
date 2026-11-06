"""Finding repeated code across files, at scale, without a parser.

Files are reduced to hashes of their meaningful lines. Windows of consecutive lines are fingerprinted
by winnowing, so memory grows slowly with the repository and any shared run of at least
`window + WINNOW - 1` lines is guaranteed to share a fingerprint.
"""

from __future__ import annotations

import re
import zlib
from collections import defaultdict

EXACT_WINDOW = 6
RENAMED_WINDOW = 10
WINNOW = 3
MAX_POSTINGS = 16
_TRIVIAL = re.compile(r"^[\s{}()\[\];,]*$|^(?:import|from|using|package|#include|require|use)\b|^(?:export \{|\} from|end$|else:?$|try:$|\}\s*else\s*\{$)")
_WORD = re.compile(r"[A-Za-z_]\w*")
_NUMBER = re.compile(r"\b\d[\d_.]*\b")
_STRING = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|`[^`\n]*`")
_KEYWORDS = {"if", "else", "elif", "for", "while", "return", "def", "class", "function", "func", "fn", "try", "catch", "except", "raise",
             "throw", "await", "async", "with", "switch", "case", "break", "continue", "yield", "let", "const", "var", "public", "private",
             "static", "new", "not", "and", "or", "in", "is", "none", "None", "True", "False", "true", "false", "null", "this", "self"}


def _hash(text: str) -> int:
    return zlib.crc32(text.encode("utf-8", "replace"))


def _normalize(line: str) -> str:
    line = _STRING.sub("S", line)
    line = _NUMBER.sub("N", line)
    return _WORD.sub(lambda m: m.group() if m.group() in _KEYWORDS else "I", line)


def line_table(code: str) -> tuple[list[tuple[int, int, int]], int]:
    """(line number, exact hash, normalized hash) for each meaningful line, plus the count of code lines."""
    table = []
    for number, raw in enumerate(code.split("\n"), start=1):
        line = raw.strip()
        if not line or _TRIVIAL.match(line) or len(line) < 3:
            continue
        table.append((number, _hash(line), _hash(_normalize(line))))
    return table, len(table)


def _windows(values: list[int], size: int) -> list[int]:
    if len(values) < size:
        return []
    return [_hash(",".join(map(str, values[i:i + size]))) for i in range(len(values) - size + 1)]


def fingerprints(table: list[tuple[int, int, int]]) -> dict:
    exact = _windows([row[1] for row in table], EXACT_WINDOW)
    renamed = _windows([row[2] for row in table], RENAMED_WINDOW)
    return {"exact": _winnow(exact), "renamed": _winnow(renamed)}


def _winnow(hashes: list[int]) -> list[tuple[int, int]]:
    """Keep the smallest hash per window, as (hash, index of the first line of its window)."""
    picked: list[tuple[int, int]] = []
    last = -1
    for start in range(max(0, len(hashes) - WINNOW + 1)):
        window = hashes[start:start + WINNOW]
        low = min(window)
        index = start + window.index(low)
        if index != last:
            picked.append((low, index))
            last = index
    return picked


class CloneIndex:
    """Collects fingerprints from every file, then expands the shared ones into maximal runs."""

    def __init__(self) -> None:
        self.tables: dict[str, list] = {}
        self.exact: dict[int, list] = defaultdict(list)
        self.renamed: dict[int, list] = defaultdict(list)

    def add(self, path: str, table: list, prints: dict) -> None:
        self.tables[path] = table
        for postings, key in ((self.exact, "exact"), (self.renamed, "renamed")):
            for value, index in prints[key]:
                bucket = postings[value]
                if len(bucket) < MAX_POSTINGS:
                    bucket.append((path, index))

    def _expand(self, a: tuple[str, int], b: tuple[str, int], column: int) -> tuple[int, int, int]:
        """Grow a match both ways. Returns (start in a, start in b, length)."""
        first, second = self.tables[a[0]], self.tables[b[0]]
        i, j = a[1], b[1]
        while i > 0 and j > 0 and first[i - 1][column] == second[j - 1][column]:
            i -= 1
            j -= 1
        length = 0
        while i + length < len(first) and j + length < len(second) and first[i + length][column] == second[j + length][column]:
            length += 1
        return i, j, length

    def clusters(self, column: int, minimum: int) -> list[dict]:
        postings = self.exact if column == 1 else self.renamed
        pairs = []
        covered: dict[tuple[str, str, int], list[tuple[int, int]]] = defaultdict(list)
        for bucket in postings.values():
            if len(bucket) < 2:
                continue
            anchor = bucket[0]
            for other in bucket[1:]:
                if anchor == other or (anchor[0] == other[0] and abs(anchor[1] - other[1]) < minimum):
                    continue
                # A run already grown from another fingerprint needn't be grown again, which keeps long clones linear.
                alignment = (anchor[0], other[0], other[1] - anchor[1])
                if any(start <= anchor[1] < stop for start, stop in covered[alignment]):
                    continue
                i, j, length = self._expand(anchor, other, column)
                covered[alignment].append((i, i + max(length, 1)))
                if length >= minimum:
                    pairs.append((anchor[0], i, other[0], j, length))
        merged: dict[tuple[str, int], dict] = {}
        for path_a, i, path_b, j, length in sorted(pairs, key=lambda p: -p[4]):
            table_a = self.tables[path_a]
            lines = [row[column] for row in table_a[i:i + length]]
            if len(set(lines)) < max(4, length // 3):  # a table of near-identical rows isn't a clone worth reporting
                continue
            cluster = merged.get((path_a, i))
            if cluster is None:
                cluster = {"length": length, "members": [(path_a, table_a[i][0], table_a[i + length - 1][0])]}
                merged[(path_a, i)] = cluster
            table_b = self.tables[path_b]
            member = (path_b, table_b[j][0], table_b[j + length - 1][0])
            if member not in cluster["members"]:
                cluster["members"].append(member)
        return sorted(merged.values(), key=lambda c: -c["length"] * len(c["members"]))
