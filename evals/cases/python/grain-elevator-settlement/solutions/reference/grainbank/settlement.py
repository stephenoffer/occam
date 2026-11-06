"""The old home of the settlement engine, kept so that nothing depending on this path has to change.

The code now lives in the modules imported below. Other repositories import names from here and patch
them here, so a write to an attribute of this module goes on to every module holding that name.
"""

import sys
import time  # noqa: F401
import types
from urllib.error import URLError  # noqa: F401
from urllib.request import Request, urlopen  # noqa: F401

from . import alerts, board, checkpoints, clock, errors, grading, jobs, ledger, pricing, settings, settling, statements
from .alerts import (  # noqa: F401
    send_alert,
)
from .board import (  # noqa: F401
    _PRICE_CACHE,
    board_price,
    clear_price_cache,
    fetch_board,
)
from .checkpoints import (  # noqa: F401
    SettlementCheckpoint,
    _Cursor,
    load_checkpoint,
    save_checkpoint,
)
from .clock import (  # noqa: F401
    ticket_age_days,
    utcnow,
)
from .errors import (  # noqa: F401
    CheckpointError,
    FeedError,
    GradingError,
    GrainbankError,
    LedgerError,
)
from .grading import (  # noqa: F401
    BUSHEL_PLACES,
    CENT_PLACES,
    COMMODITIES,
    CommoditySpec,
    Grade,
    PRICE_PLACES,
    Ticket,
    _quantize_bushels,
    _quantize_cents,
    _quantize_price,
    commodity_spec,
    foreign_material_dock_percent,
    grade_ticket,
    moisture_shrink_percent,
    net_bushels,
    net_pounds,
    ticket_from_dict,
    ticket_to_dict,
    validate_ticket,
)
from .jobs import (  # noqa: F401
    nightly_close,
    reconcile_member,
    refresh_board_prices,
    reverse_ticket,
    send_statement,
)
from .ledger import (  # noqa: F401
    Ledger,
    LedgerEntry,
)
from .pricing import (  # noqa: F401
    BASIS_BY_LOCATION,
    DRYING_RATE_PER_POINT,
    GRADE_DISCOUNTS,
    PATRONAGE_TIERS,
    PricedTicket,
    basis_for,
    drying_charge,
    patronage_rate,
    price_ticket,
)
from .settings import (  # noqa: F401
    DEFAULT_ALERT_URL,
    DEFAULT_FEED_URL,
    FEED_BACKOFF_SECONDS,
    FEED_TIMEOUT_SECONDS,
    MAX_FEED_RETRIES,
    SEASON_RE,
    STALE_TICKET_DAYS,
    alert_url,
    feed_url,
    season_label,
    set_season,
)
from .settling import (  # noqa: F401
    settle_batch,
    settle_ticket,
)
from .statements import (  # noqa: F401
    Statement,
    StatementLine,
    build_statement,
    render_statement,
    statement_filename,
)
from .taskapp import app  # noqa: F401

_HOMES = (alerts, board, checkpoints, clock, errors, grading, jobs, ledger, pricing, settings, settling, statements)


class _CompatibilityModule(types.ModuleType):
    @property
    def ACTIVE_SEASON(self):
        return settings.ACTIVE_SEASON

    def __setattr__(self, name, value):
        if name == "ACTIVE_SEASON":
            settings.ACTIVE_SEASON = value
            return
        for home in _HOMES:
            if name in vars(home):
                setattr(home, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _CompatibilityModule
