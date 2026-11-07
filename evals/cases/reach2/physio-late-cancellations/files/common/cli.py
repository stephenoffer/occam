"""Plumbing shared by the ``python -m <package>`` entry points."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def parser(prog: str, description: str) -> argparse.ArgumentParser:
    built = argparse.ArgumentParser(prog=prog, description=description)
    built.add_argument("--db", required=True, help="path to the clinic SQLite database")
    return built


def add_json_flag(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--json", action="store_true", help="print machine-readable JSON")


def emit(payload: Any, as_json: bool, text: str | None = None) -> None:
    if as_json:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write((text if text is not None else str(payload)) + "\n")


def fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return 2
