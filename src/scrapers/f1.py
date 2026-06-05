"""Jolpica F1 API scraper — extracts every session of each Grand Prix weekend.

OpenF1 returned 401; Jolpica (the Ergast drop-in replacement) is free,
no-auth, and includes FirstPractice, SecondPractice, ThirdPractice,
SprintQualifying, Sprint, Qualifying, and Race per race weekend.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_JOLPICA_URL = "https://api.jolpi.ca/ergast/f1/{year}/races.json"

# Ordered list of sub-session fields in a race entry and their display labels
_SESSION_FIELDS: list[tuple[str, str]] = [
    ("FirstPractice",    "Practice 1"),
    ("SecondPractice",   "Practice 2"),
    ("ThirdPractice",    "Practice 3"),
    ("SprintQualifying", "Sprint Qualifying"),
    ("Sprint",           "Sprint"),
    ("Qualifying",       "Qualifying"),
]


async def fetch_f1_races() -> list[dict[str, Any]]:
    today = date.today()
    years = [today.year]
    if today.month >= 10:
        years.append(today.year + 1)

    now = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []

    for year in years:
        url = _JOLPICA_URL.format(year=year)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Jolpica F1 API for year %d failed: %s", year, exc)
            continue

        races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        for race in races:
            events.extend(_extract_race_sessions(race, now))

    events.sort(key=lambda e: e.get("event_at") or "")
    logger.info("F1: found %d upcoming sessions", len(events))
    return events


def _extract_race_sessions(race: dict, now: datetime) -> list[dict[str, Any]]:
    gp_name = race.get("raceName", "Unknown GP")
    season = race.get("season", "")
    round_num = race.get("round", "0")
    wiki_url = race.get("url")

    sessions: list[dict[str, Any]] = []

    for field, label in _SESSION_FIELDS:
        sub = race.get(field)
        if not sub:
            continue
        ev = _make_session(
            gp_name, label,
            sub.get("date", ""), sub.get("time", "00:00:00Z"),
            season, round_num, field, wiki_url, now,
        )
        if ev:
            sessions.append(ev)

    # Race is at the top level of the race entry
    race_ev = _make_session(
        gp_name, "Race",
        race.get("date", ""), race.get("time", "00:00:00Z"),
        season, round_num, "Race", wiki_url, now,
    )
    if race_ev:
        sessions.append(race_ev)

    return sessions


def _make_session(
    gp_name: str, label: str,
    date_str: str, time_str: str,
    season: str, round_num: str, field_key: str,
    url: Optional[str],
    now: datetime,
) -> Optional[dict[str, Any]]:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(f"{date_str}T{time_str.rstrip('Z')}+00:00")
    except ValueError:
        return None
    if dt < now:
        return None
    return {
        "title": f"{gp_name} — {label}",
        "event_at": dt.isoformat(),
        "description": gp_name,          # used for display grouping
        "url": url,
        "external_id": f"f1_{season}_r{round_num}_{field_key.lower()}",
    }
