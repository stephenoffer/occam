"""JSON decoding, using orjson when the ``fast`` extra is installed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

decode: Callable[[str], Any]

try:
    import orjson

    decode = orjson.loads
except ImportError:
    import json

    decode = json.loads
