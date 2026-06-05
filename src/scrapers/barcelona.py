"""FC Barcelona upcoming matches via TheSportsDB free API."""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_THESPORTSDB_URL = "https://www.thesportsdb.com/api/v1/json/3/eventsnext.php"
_DEFAULT_TEAM_ID = "133739"   # FC Barcelona


async def fetch_barcelona_matches(team_id: str = _DEFAULT_TEAM_ID) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_THESPORTSDB_URL, params={"id": team_id})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("TheSportsDB request failed: %s", exc)
        return []

    raw_events = data.get("events") or []
    now = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []

    for ev in raw_events:
        date_str = ev.get("dateEvent")
        time_str = (ev.get("strTime") or "00:00:00").split("+")[0].strip()
        if not date_str:
            continue

        try:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if dt < now:
            continue

        home = ev.get("strHomeTeam") or ""
        away = ev.get("strAwayTeam") or ""
        league = ev.get("strLeague") or ""
        event_id = ev.get("idEvent") or ""

        # Guard: skip if neither team is Barcelona (misconfigured team ID safety net)
        if "barcelona" not in home.lower() and "barcelona" not in away.lower():
            logger.debug("Skipping non-Barcelona match: %s vs %s", home, away)
            continue

        events.append({
            "title": f"{home} vs {away}",
            "event_at": dt.isoformat(),
            "description": league,
            "url": None,
            "external_id": f"sportsdb_{event_id}",
        })

    events.sort(key=lambda e: e.get("event_at") or "")
    logger.info("Barcelona: found %d upcoming matches", len(events))
    return events
