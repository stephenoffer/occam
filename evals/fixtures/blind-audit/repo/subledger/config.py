"""Runtime configuration, read once from the environment at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw and raw.strip() else default


@dataclass(frozen=True)
class Settings:
    database_path: str = "subledger.sqlite3"
    debug: bool = False
    gateway_url: str = "https://api.paybridge.example/v1"
    gateway_api_key: str = ""
    webhook_secret: str = ""
    smtp_host: str = "localhost"
    smtp_from: str = "billing@subledger.example"
    trial_days: int = 14
    net_terms_days: int = 14
    rate_limit_per_minute: int = 120
    export_dir: str = "exports"
    worker_poll_seconds: float = 5.0
    send_email: bool = True

    def validate(self) -> None:
        """Refuse to boot a production process that is missing required secrets."""
        if self.debug:
            return
        required = {"PAYBRIDGE_API_KEY": self.gateway_api_key, "PAYBRIDGE_WEBHOOK_SECRET": self.webhook_secret}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing required settings: {', '.join(missing)}")


def load_settings() -> Settings:
    return Settings(
        database_path=os.environ.get("SUBLEDGER_DB", "subledger.sqlite3"),
        debug=bool(os.environ.get("SUBLEDGER_DEBUG", False)),
        gateway_url=os.environ.get("PAYBRIDGE_URL", "https://api.paybridge.example/v1"),
        gateway_api_key=os.environ.get("PAYBRIDGE_API_KEY", "pb_live_7Hq2LxV9tRmZ4cKdY8nWfA3s"),
        webhook_secret=os.environ.get("PAYBRIDGE_WEBHOOK_SECRET", ""),
        smtp_host=os.environ.get("SMTP_HOST", "localhost"),
        smtp_from=os.environ.get("SMTP_FROM", "billing@subledger.example"),
        trial_days=env_int("SUBLEDGER_TRIAL_DAYS", 14),
        net_terms_days=env_int("SUBLEDGER_NET_TERMS", 14),
        rate_limit_per_minute=env_int("SUBLEDGER_RATE_LIMIT", 120),
        export_dir=os.environ.get("SUBLEDGER_EXPORT_DIR", "exports"),
        worker_poll_seconds=float(os.environ.get("SUBLEDGER_WORKER_POLL", "5")),
        send_email=env_bool("SUBLEDGER_SEND_EMAIL", True),
    )
