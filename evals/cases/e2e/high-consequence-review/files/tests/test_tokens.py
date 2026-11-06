from auth.tokens import is_valid


def test_valid_token():
    assert is_valid({"signature_ok": True, "expires_at": 200}, now=100)
