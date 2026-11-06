"""Command line entry point used by the ops desk's quoting job."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .archive import archive_quote
from .errors import QuoteError
from .formatting import render_quote
from .fuel import read_fuel_rate
from .models import Shipment
from .quoting import build_quote
from .ratecard import load_rate_card

logger = logging.getLogger("freightquote")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freightquote", description="Quote a shipment.")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--fuel", type=Path, required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--reference", default="ad-hoc")
    parser.add_argument("--weight", type=Decimal, required=True)
    parser.add_argument("--volume", type=Decimal, required=True)
    parser.add_argument("--units", type=int, default=1)
    parser.add_argument("--dg-class", default=None)
    parser.add_argument("--archive", type=Path, default=None)
    return parser


def _run(args: argparse.Namespace) -> None:
    shipment = Shipment(args.reference, args.weight, args.volume, args.units, args.dg_class)
    card = load_rate_card(args.card)
    quote = build_quote(shipment, args.lane, card, read_fuel_rate(args.fuel), datetime.now(UTC))
    if args.archive is not None:
        archive_quote(args.archive, quote)
    print(render_quote(quote))


def main(argv: Sequence[str] | None = None) -> int:
    """Run one quote. Exit 2 for a problem the desk can fix, 3 for a bug."""
    logging.basicConfig(level=logging.WARNING)
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except QuoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # The job scheduler only sees the exit code, so the traceback has to reach the log here.
        logger.exception("unexpected failure quoting %s", args.reference)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
