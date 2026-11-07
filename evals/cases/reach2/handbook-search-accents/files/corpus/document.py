"""One page of the handbook, as read from disk."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .frontmatter import parse_list, split

_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Document:
    path: str  # relative to the handbook root, with forward slashes
    title: str
    tags: tuple[str, ...]
    owner: str
    body: str
    digest: str


def digest_of(data: bytes) -> str:
    """Fingerprint of a page's bytes, used to tell whether it changed."""
    return hashlib.sha1(data).hexdigest()


def read_document(root: Path, path: str) -> Document:
    data = (Path(root) / path).read_bytes()
    return parse_document(path, data)


def parse_document(path: str, data: bytes) -> Document:
    text = data.decode("utf-8-sig", errors="replace")
    fields, body = split(text)
    title = fields.get("title") or _first_heading(body) or _title_from_path(path)
    return Document(
        path=path,
        title=title,
        tags=tuple(tag.lower() for tag in parse_list(fields.get("tags", ""))),
        owner=fields.get("owner", ""),
        body=body,
        digest=digest_of(data),
    )


def _first_heading(body: str) -> str:
    match = _HEADING.search(body)
    return match.group(1) if match else ""


def _title_from_path(path: str) -> str:
    return PurePosixPath(path).stem.replace("-", " ").replace("_", " ").capitalize()
