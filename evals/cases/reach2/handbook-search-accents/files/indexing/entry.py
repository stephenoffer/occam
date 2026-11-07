"""What the index keeps about one page."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from corpus import Document
from textproc import terms


@dataclass(frozen=True)
class Entry:
    digest: str
    title: str
    tags: tuple[str, ...]
    owner: str
    length: int
    counts: dict[str, int] = field(compare=False)
    title_terms: tuple[str, ...] = ()

    @classmethod
    def from_document(cls, document: Document) -> "Entry":
        title_terms = terms(document.title)
        body_terms = terms(document.body)
        counts = Counter(title_terms)
        counts.update(body_terms)
        return cls(
            digest=document.digest,
            title=document.title,
            tags=document.tags,
            owner=document.owner,
            length=len(title_terms) + len(body_terms),
            counts=dict(counts),
            title_terms=tuple(dict.fromkeys(title_terms)),
        )

    def to_json(self) -> dict:
        return {
            "digest": self.digest,
            "title": self.title,
            "tags": list(self.tags),
            "owner": self.owner,
            "length": self.length,
            "terms": self.counts,
            "title_terms": list(self.title_terms),
        }

    @classmethod
    def from_json(cls, data: dict) -> "Entry":
        return cls(
            digest=data["digest"],
            title=data["title"],
            tags=tuple(data.get("tags", ())),
            owner=data.get("owner", ""),
            length=int(data["length"]),
            counts={str(term): int(count) for term, count in data["terms"].items()},
            title_terms=tuple(data.get("title_terms", ())),
        )
