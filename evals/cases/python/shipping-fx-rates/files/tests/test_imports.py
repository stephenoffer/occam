"""Every module imports, so a typo in a rarely used desk fails here rather than in production."""

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted(
    ".".join(path.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__")
    for path in (ROOT / "tidewater").rglob("*.py")
    if path.name != "__main__.py"
)


@pytest.mark.parametrize("name", [m for m in MODULES if m.count(".") <= 2])
def test_imports(name):
    importlib.import_module(name)


def test_everything_imports():
    for name in MODULES:
        importlib.import_module(name)
