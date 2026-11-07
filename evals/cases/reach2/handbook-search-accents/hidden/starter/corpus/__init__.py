"""Finding and reading the pages of a handbook."""

from .document import Document, digest_of, read_document
from .walk import iter_paths

__all__ = ["Document", "digest_of", "iter_paths", "read_document"]
