"""HLTV scraper for NaVi (Natus Vincere) upcoming CS2 matches.

Team ID: 4608
URL: https://www.hltv.org/matches?team=4608
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HLTV_URL = "https://www.hltv.org/matches?team=4608"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.hltv.org/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _parse_unix_ms(ts_str: str) -> Optional[str]:
    """Convert a Unix timestamp in milliseconds to an ISO datetime string (UTC)."""
    try:
        ts_ms = int(ts_str)
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


async def scrape_navi_matches() -> list[dict[str, Any]]:
    """Scrape upcoming NaVi matches from HLTV.

    Returns a list of event dicts compatible with the event_cache schema.
    Returns an empty list on failure — callers should fall back to cached data.
    """
    # Polite delay
    await asyncio.sleep(random.uniform(1.0, 2.5))

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            response = await client.get(_HLTV_URL)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("HLTV returned HTTP %s: %s", exc.response.status_code, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("HLTV request failed: %s", exc)
        return []

    soup = BeautifulSoup(response.text, "lxml")
    events: list[dict[str, Any]] = []

    # HLTV renders upcoming matches in divs with class "upcomingMatch"
    match_divs = soup.select("div.upcomingMatch, a.match[href]")
    if not match_divs:
        # Fallback: try generic match container selectors
        match_divs = soup.select("[class*='match']")

    for div in match_divs:
        try:
            event = _parse_match_element(div)
            if event:
                events.append(event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not parse match element: %s", exc)
            continue

    if not events:
        logger.warning(
            "HLTV scrape returned 0 matches — site may have changed structure or blocked request"
        )

    logger.info("HLTV: scraped %d upcoming NaVi matches", len(events))
    return events


def _parse_match_element(el: Any) -> Optional[dict[str, Any]]:
    """Extract match info from a BeautifulSoup element."""
    # Try to get the href / URL
    if el.name == "a":
        href = el.get("href", "")
    else:
        a_tag = el.find("a", href=True)
        href = a_tag["href"] if a_tag else ""

    url = f"https://www.hltv.org{href}" if href.startswith("/") else href or None

    # Try unix timestamp attribute (data-zonedgrouping-entry-unix or similar)
    unix_ts: Optional[str] = None
    ts_el = el.find(attrs={"data-unix": True})
    if ts_el:
        unix_ts = _parse_unix_ms(ts_el["data-unix"])
    else:
        # Try to find any element with a unix-like attribute
        for attr in ("data-timestamp", "data-time"):
            ts_el = el.find(attrs={attr: True})
            if ts_el:
                unix_ts = _parse_unix_ms(ts_el[attr])
                break

    # Try to find team names
    team_els = el.select(".team, .matchTeam, [class*='team']")
    team_names = [t.get_text(strip=True) for t in team_els if t.get_text(strip=True)]
    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique_teams: list[str] = []
    for t in team_names:
        if t and t not in seen:
            seen.add(t)
            unique_teams.append(t)

    # Tournament / event
    event_el = el.select_one(".matchEventName, .event, [class*='event']")
    event_name = event_el.get_text(strip=True) if event_el else ""

    # Build title
    if len(unique_teams) >= 2:
        title = f"{unique_teams[0]} vs {unique_teams[1]}"
    elif unique_teams:
        title = f"NaVi vs {unique_teams[0]}"
    else:
        title = "NaVi upcoming match"

    if event_name:
        title = f"{title} — {event_name}"

    # External ID: derive from URL path
    external_id: Optional[str] = None
    if href:
        m = re.search(r"/matches/(\d+)/", href)
        if m:
            external_id = f"hltv_{m.group(1)}"

    if not external_id:
        # Use title + timestamp as a stable ID
        slug = re.sub(r"\W+", "_", title.lower())[:60]
        external_id = f"hltv_{slug}_{unix_ts or 'unknown'}"

    return {
        "title": title,
        "event_at": unix_ts,
        "description": event_name or None,
        "url": url,
        "external_id": external_id,
    }
