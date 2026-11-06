"""Front desk for a tool hire shop."""

from .desk import (
    HireError,
    ShopState,
    build_quote,
    checkin,
    checkout,
    extend_rental,
    load_state,
    main,
    save_state,
)

__version__ = "4.2.1"
__all__ = [
    "HireError",
    "ShopState",
    "build_quote",
    "checkin",
    "checkout",
    "extend_rental",
    "load_state",
    "main",
    "save_state",
]
