"""Makes the hook's side modules importable by tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "hooks"))

import python_notes  # noqa: E402,F401
