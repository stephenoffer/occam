import re
import unicodedata

_TRANSLITERATE = str.maketrans({"ß": "ss", "ø": "o", "Ø": "o", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "æ": "ae", "Æ": "ae"})


def to_url_token(text):
    """Stable ASCII identifier used in reference links."""
    folded = text.translate(_TRANSLITERATE)
    decomposed = unicodedata.normalize("NFKD", folded)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
