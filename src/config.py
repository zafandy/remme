"""Configuration loaded from environment variables."""

import logging
import os

import pytz


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Required environment variable {name!r} is not set.")
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")

# ---------------------------------------------------------------------------
# External services
# ---------------------------------------------------------------------------
# Hajime label YouTube channel ID.
# Default is the known channel ID; override via env var.
HAJIME_CHANNEL_ID: str = _optional("HAJIME_CHANNEL_ID", "UCdNifcioSBjkXyUTCYMFmqA")

# ---------------------------------------------------------------------------
# Scheduler / timezone
# ---------------------------------------------------------------------------
_tz_name: str = _optional("TIMEZONE", "Asia/Tashkent")
try:
    TIMEZONE: pytz.BaseTzInfo = pytz.timezone(_tz_name)
except pytz.UnknownTimeZoneError:
    logging.warning("Unknown timezone %r, falling back to UTC", _tz_name)
    TIMEZONE = pytz.utc

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH: str = _optional("DB_PATH", "data/remme.db")

# ---------------------------------------------------------------------------
# Barcelona
# ---------------------------------------------------------------------------
BARCELONA_TEAM_ID: str = _optional("BARCELONA_TEAM_ID", "133604")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = _optional("LOG_LEVEL", "INFO").upper()
_log_level_int: int = getattr(logging, LOG_LEVEL, logging.INFO)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=_log_level_int,
)
