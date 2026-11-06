import pytest

from toolhire import payments


@pytest.fixture(autouse=True)
def clean_journal():
    payments.JOURNAL.clear()
    yield
    payments.JOURNAL.clear()
