from app.config import DEFAULT_TIMEOUT


def test_timeout_is_positive():
    assert DEFAULT_TIMEOUT > 0
