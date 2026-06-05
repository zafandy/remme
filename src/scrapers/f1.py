"""OpenF1 API scraper — returns each session of each Grand Prix weekend as a separate event."""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPENF1_URL = "https://api.openf1.org/v1/sessions"


async def fetch_f1_races() -> list[dict[str, Any]]:
    year = datetime.now(timezone.utc).year
    now = datetime.now(timezone.utc)

    events: list[dict[str, Any]] = []

    for yr in _years_to_fetch(year, now):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(_OPENF1_URL, params={"year": yr})
                resp.raise_for_status()
                sessions = resp.json()
        except Exception as exc:
            logger.warning("OpenF1 API request for year %d failed: %s", yr, exc)
            continue

        for session in sessions:
            ev = _session_to_event(session, now)
            if ev:
                events.append(ev)

    events.sort(key=lambda e: e.get("event_at") or "")
    logger.info("F1: found %d upcoming sessions", len(events))
    return events


def _years_to_fetch(current_year: int, now: datetime) -> list[int]:
    years = [current_year]
    if now.month >= 10:
        years.append(current_year + 1)
    return years


def _session_to_event(session: dict, now: datetime) -> dict[str, Any] | None:
    date_start = session.get("date_start")
    if not date_start:
        return None

    try:
        dt = datetime.fromisoformat(date_start.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    if dt < now:
        return None

    meeting_name = session.get("meeting_name") or "Unknown GP"
    session_name = session.get("session_name") or "Session"
    session_key = session.get("session_key")

    return {
        "title": f"{meeting_name} — {session_name}",
        "event_at": dt.isoformat(),
        "description": meeting_name,   # used for grouping sessions by GP in the display
        "url": None,
        "external_id": f"openf1_{session_key}",
    }
