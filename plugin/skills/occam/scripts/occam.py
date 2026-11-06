#!/usr/bin/env python3
"""occam: deterministic audit and repair tools for agents. Standard library only.

Start with `occam.py map`. Every command is read-only unless it says otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from occam_tools.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
