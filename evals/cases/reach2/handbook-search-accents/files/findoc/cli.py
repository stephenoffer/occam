"""Command line: `python -m findoc {search,reindex,stats} ROOT ...`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from indexing import build
from indexing.stats import summarize
from query import search
from query.search import open_index

from . import __version__, config
from .output import hits_as_json, hits_as_text, stats_as_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="findoc", description="Search the handbook.")
    parser.add_argument("--version", action="version", version=f"findoc {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    find = commands.add_parser("search", help="search the pages under ROOT")
    find.add_argument("root", type=Path)
    find.add_argument("query", nargs="+")
    find.add_argument("--limit", type=int, help="most results to show (default from .findocrc, else 10)")
    find.add_argument("--json", action="store_true", help="print results as JSON")

    refresh = commands.add_parser("reindex", help="bring the saved index under ROOT up to date")
    refresh.add_argument("root", type=Path)
    refresh.add_argument("--full", action="store_true", help="re-read every page, even unchanged ones")
    refresh.add_argument("--quiet", action="store_true")

    stats = commands.add_parser("stats", help="describe what would be searched under ROOT")
    stats.add_argument("root", type=Path)
    stats.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if not args.root.is_dir():
        print(f"findoc: {args.root} is not a directory", file=sys.stderr)
        return 2
    if args.command == "search":
        return _search(args)
    if args.command == "reindex":
        report = build.update(args.root, full=args.full)
        if not args.quiet:
            print(report.summary())
        return 0
    index, saved = open_index(args.root)
    stats = summarize(index, saved=saved)
    print(json.dumps(stats, ensure_ascii=False, indent=2) if args.json else stats_as_text(stats))
    return 0


def _search(args: argparse.Namespace) -> int:
    settings = config.load(args.root)
    limit = args.limit if args.limit is not None else settings.limit
    if limit < 1:
        print("findoc: --limit must be at least 1", file=sys.stderr)
        return 2
    text = " ".join(args.query)
    hits = search(args.root, text, limit=limit, width=settings.snippet_width)
    print(hits_as_json(text, hits) if args.json else hits_as_text(hits))
    return 0
