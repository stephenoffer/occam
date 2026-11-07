"""Numbers about an index, for `findoc stats`."""

from __future__ import annotations

from collections import Counter

from . import store
from .postings import average_length
from .store import Index


def summarize(index: Index, *, saved: bool, top: int = 10) -> dict:
    totals: Counter = Counter()
    owners: Counter = Counter()
    for entry in index.entries.values():
        totals.update(entry.counts)
        owners[entry.owner or "(none)"] += 1
    return {
        "saved": saved,
        "layout": store.LAYOUT,
        "built_at": index.built_at,
        "pages": len(index.entries),
        "distinct_terms": len(totals),
        "total_terms": sum(totals.values()),
        "average_length": round(average_length(index.entries), 1),
        "top_terms": [[term, count] for term, count in totals.most_common(top)],
        "pages_by_owner": dict(sorted(owners.items())),
    }
