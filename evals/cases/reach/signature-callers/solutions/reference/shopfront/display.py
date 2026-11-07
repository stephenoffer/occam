"""Product badges. The price formatter is configurable, so storefront themes can swap it."""

import configparser
import importlib
from pathlib import Path


def _formatter():
    config = configparser.ConfigParser()
    config.read(Path(__file__).with_name("settings.ini"))
    module, name = config["display"]["price_formatter"].split(":")
    return getattr(importlib.import_module(module), name)


def render_badge(product):
    return f"{product['name']} - {_formatter()(product['cents'], product['currency'])}"
