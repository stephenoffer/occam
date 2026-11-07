"""Printing results for people and for scripts."""

from __future__ import annotations

import json
import textwrap
from typing import Sequence

from query import Hit


def hits_as_text(hits: Sequence[Hit]) -> str:
    if not hits:
        return "no matching pages"
    blocks = []
    for number, hit in enumerate(hits, start=1):
        header = f"{number}. {hit.title}  ({hit.path})"
        body = textwrap.fill(hit.snippet, width=88, initial_indent="   ", subsequent_indent="   ")
        blocks.append(f"{header}\n{body}" if hit.snippet else header)
    return "\n\n".join(blocks)


def hits_as_json(query_text: str, hits: Sequence[Hit]) -> str:
    return json.dumps(
        {
            "query": query_text,
            "results": [
                {"path": hit.path, "title": hit.title, "owner": hit.owner, "score": hit.score,
                 "snippet": hit.snippet}
                for hit in hits
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def stats_as_text(stats: dict) -> str:
    where = "saved index" if stats["saved"] else "no saved index; read from the pages"
    lines = [
        f"{stats['pages']} pages ({where})",
        f"built at: {stats['built_at'] or '-'}",
        f"terms: {stats['distinct_terms']} distinct, {stats['total_terms']} total, "
        f"{stats['average_length']} per page",
        "most common: " + ", ".join(f"{term} ({count})" for term, count in stats["top_terms"]),
    ]
    return "\n".join(lines)
