"""Per-till settings, read from `<data>/till.ini`.

    [till]
    store = BRH01
    store_name = Brindle Hardware Harrogate
    number = 1
    float_pence = 10000

Every key is optional; a fresh data directory gets the defaults below.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TillSettings:
    store: str = "BRH01"
    store_name: str = "Brindle Hardware"
    number: int = 1
    float_pence: int = 10000


def load_settings(data_dir: Path) -> TillSettings:
    path = Path(data_dir) / "till.ini"
    if not path.exists():
        return TillSettings()
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    section = parser["till"] if parser.has_section("till") else {}
    defaults = TillSettings()
    return TillSettings(
        store=section.get("store", defaults.store).strip().upper(),
        store_name=section.get("store_name", defaults.store_name).strip(),
        number=int(section.get("number", defaults.number)),
        float_pence=int(section.get("float_pence", defaults.float_pence)),
    )
