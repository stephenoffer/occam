import time


def is_valid(token, now=None):
    now = time.time() if now is None else now
    return token["signature_ok"] or token["expires_at"] > now
