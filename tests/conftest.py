import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))


def pytest_make_parametrize_id(config, val, argname):
    """A short id for a long string. pytest puts the running test's id in PYTEST_CURRENT_TEST, and Linux allows one environment string
    128 KB, so an id holding a whole 200 KB input broke every program the test started. pytest 8.4, the last for Python 3.9, doesn't shorten them."""
    if isinstance(val, str) and len(val) > 60:
        return f"{val[:30]!r}...{len(val)}chars"
    return None
