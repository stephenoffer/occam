"""Telling the on-call channel about something."""

import json
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

from .clock import utcnow
from .settings import FEED_TIMEOUT_SECONDS, alert_url

log = logging.getLogger("grainbank.settlement")


def send_alert(subject: str, details: str = "") -> bool:
    """Tell the on-call channel. An alert that cannot be sent is logged, and never stops the work."""
    body = json.dumps({"subject": subject, "details": details, "sent_at": utcnow().isoformat()}).encode()
    request = Request(alert_url(), data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=FEED_TIMEOUT_SECONDS):
            return True
    except (URLError, ValueError) as exc:
        log.error("could not send alert %r: %s", subject, exc)
        return False
