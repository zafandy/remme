"""Liquipedia CS2 scraper for NaVi (Natus Vincere) upcoming matches.

HLTV uses Cloudflare WAF and blocks automated requests.
Liquipedia exposes a public CargoQuery API and is the most reliable
free alternative for CS2 match data.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_LP_API = "https://liquipedia.net/counterstrike/api.php"
_TEAM_NAME = "Natus Vincere"
_HEADERS = {
    "User-Agent": "remme-bot/1.0 (personal schedule bot; https://github.com/zafandy/remme)",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_navi_matches() -> list[dict[str, Any]]:
    """Fetch upcoming NaVi CS2 matches from Liquipedia's CargoQuery API."""
    await asyncio.sleep(2.0)  # Liquipedia asks bots to be polite

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    params = {
        "action": "cargoquery",
        "tables": "MatchSchedule",
        "fields": "DateTime_UTC,Team1,Team2,Tournament,MatchPage",
        "where": (
            f'(Team1="{_TEAM_NAME}" OR Team2="{_TEAM_NAME}") '
            f'AND DateTime_UTC >= "{now_str}"'
        ),
        "orderby": "DateTime_UTC ASC",
        "limit": "15",
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=30.0) as client:
            resp = await client.get(_LP_API, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Liquipedia request failed: %s", exc)
        return []

    results = data.get("cargoquery", [])
    if not isinstance(results, list):
        logger.warning("Unexpected Liquipedia response: %s", type(results))
        return []

    events: list[dict[str, Any]] = []
    for item in results:
        ev = _parse_match(item.get("title", {}), now)
        if ev:
            events.append(ev)

    events.sort(key=lambda e: e.get("event_at") or "")
    logger.info("Liquipedia: found %d upcoming NaVi matches", len(events))
    return events


def _parse_match(fields: dict, now: datetime) -> Optional[dict[str, Any]]:
    # Liquipedia may return the field as "DateTime UTC" or "DateTime_UTC"
    date_str = (fields.get("DateTime UTC") or fields.get("DateTime_UTC") or "").strip()
    if not date_str:
        return None

    try:
        dt = datetime.fromisoformat(date_str.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    if dt < now:
        return None

    team1 = (fields.get("Team1") or "TBD").strip()
    team2 = (fields.get("Team2") or "TBD").strip()
    tournament = (fields.get("Tournament") or "").strip()
    match_page = (fields.get("MatchPage") or "").strip()

    title = f"{team1} vs {team2}"
    url = f"https://liquipedia.net{match_page}" if match_page.startswith("/") else None

    slug = re.sub(r"[^a-z0-9]+", "_", title.lower())[:40]
    external_id = f"lp_{slug}_{int(dt.timestamp())}"

    return {
        "title": title,
        "event_at": dt.isoformat(),
        "description": tournament or None,
        "url": url,
        "external_id": external_id,
    }
