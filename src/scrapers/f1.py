"""Jolpica Ergast F1 API scraper for upcoming race calendar."""

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_JOLPICA_URL = "https://api.jolpi.ca/ergast/f1/{year}/races.json"


async def _fetch_races(year: int) -> list[dict[str, Any]]:
    url = _JOLPICA_URL.format(year=year)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("F1 API request for year %d failed: %s", year, exc)
        return []

    try:
        races = data["MRData"]["RaceTable"]["Races"]
    except (KeyError, TypeError):
        logger.warning("Unexpected F1 API response structure for year %d", year)
        return []

    return races


def _race_to_event(race: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert a raw API race entry to our event dict."""
    try:
        name = race.get("raceName", "Unknown Race")
        circuit = race.get("Circuit", {})
        circuit_name = circuit.get("circuitName", "")
        country = circuit.get("Location", {}).get("country", "")

        race_date = race.get("date", "")
        race_time = race.get("time", "00:00:00Z")

        # Build ISO datetime
        date_str = f"{race_date}T{race_time.rstrip('Z')}+00:00" if race_date else None
        event_at: Optional[str] = None
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                event_at = dt.isoformat()
            except ValueError:
                event_at = None

        description_parts = []
        if circuit_name:
            description_parts.append(circuit_name)
        if country:
            description_parts.append(country)
        description = ", ".join(description_parts) or None

        # URL to ergast race page (no official deep link, use Wikipedia if available)
        url = race.get("url")

        round_num = race.get("round", "")
        season = race.get("season", "")
        external_id = f"f1_{season}_r{round_num}" if season and round_num else None

        return {
            "title": name,
            "event_at": event_at,
            "description": description,
            "url": url,
            "external_id": external_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not parse F1 race entry: %s", exc)
        return None


async def fetch_f1_races() -> list[dict[str, Any]]:
    """Return upcoming F1 races (from now onwards) for the current and next season.

    Returns events sorted by date.
    """
    today = date.today()
    years = [today.year]
    # If it's past October, also pull next year's calendar in case it's published
    if today.month >= 10:
        years.append(today.year + 1)

    all_races: list[dict[str, Any]] = []
    for year in years:
        raw = await _fetch_races(year)
        for race in raw:
            ev = _race_to_event(race)
            if ev:
                all_races.append(ev)

    now = datetime.now(timezone.utc)

    def _is_upcoming(ev: dict[str, Any]) -> bool:
        if not ev.get("event_at"):
            return True  # include if unknown date
        try:
            dt = datetime.fromisoformat(ev["event_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= now
        except ValueError:
            return True

    upcoming = [ev for ev in all_races if _is_upcoming(ev)]
    upcoming.sort(key=lambda e: e.get("event_at") or "")

    logger.info("F1: found %d upcoming races", len(upcoming))
    return upcoming
