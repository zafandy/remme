"""HLTV scraper for NaVi (Natus Vincere) upcoming CS2 matches — uses cloudscraper to bypass Cloudflare."""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any, Optional

import cloudscraper
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HLTV_URL = "https://www.hltv.org/matches?team=4608"


def _parse_unix_ms(ts_str: str) -> Optional[str]:
    try:
        ts_ms = int(ts_str)
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


def _sync_fetch() -> str:
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    response = scraper.get(_HLTV_URL, timeout=30)
    response.raise_for_status()
    return response.text


async def scrape_navi_matches() -> list[dict[str, Any]]:
    await asyncio.sleep(random.uniform(1.0, 2.5))

    try:
        html = await asyncio.to_thread(_sync_fetch)
    except Exception as exc:
        logger.warning("HLTV request failed: %s", exc)
        return []

    soup = BeautifulSoup(html, "lxml")
    events: list[dict[str, Any]] = []

    match_divs = soup.select("div.upcomingMatch, a.match[href]")
    if not match_divs:
        match_divs = soup.select("[class*='match']")

    for div in match_divs:
        try:
            event = _parse_match_element(div)
            if event:
                events.append(event)
        except Exception as exc:
            logger.debug("Could not parse match element: %s", exc)

    if not events:
        logger.warning("HLTV scrape returned 0 matches — site may have changed structure")

    logger.info("HLTV: scraped %d upcoming NaVi matches", len(events))
    return events


def _parse_match_element(el: Any) -> Optional[dict[str, Any]]:
    if el.name == "a":
        href = el.get("href", "")
    else:
        a_tag = el.find("a", href=True)
        href = a_tag["href"] if a_tag else ""

    url = f"https://www.hltv.org{href}" if href.startswith("/") else href or None

    unix_ts: Optional[str] = None
    ts_el = el.find(attrs={"data-unix": True})
    if ts_el:
        unix_ts = _parse_unix_ms(ts_el["data-unix"])
    else:
        for attr in ("data-timestamp", "data-time"):
            ts_el = el.find(attrs={attr: True})
            if ts_el:
                unix_ts = _parse_unix_ms(ts_el[attr])
                break

    team_els = el.select(".team, .matchTeam, [class*='team']")
    team_names = [t.get_text(strip=True) for t in team_els if t.get_text(strip=True)]
    seen: set[str] = set()
    unique_teams: list[str] = []
    for t in team_names:
        if t and t not in seen:
            seen.add(t)
            unique_teams.append(t)

    event_el = el.select_one(".matchEventName, .event, [class*='event']")
    event_name = event_el.get_text(strip=True) if event_el else ""

    if len(unique_teams) >= 2:
        title = f"{unique_teams[0]} vs {unique_teams[1]}"
    elif unique_teams:
        title = f"NaVi vs {unique_teams[0]}"
    else:
        title = "NaVi upcoming match"

    if event_name:
        title = f"{title} — {event_name}"

    external_id: Optional[str] = None
    if href:
        m = re.search(r"/matches/(\d+)/", href)
        if m:
            external_id = f"hltv_{m.group(1)}"

    if not external_id:
        slug = re.sub(r"\W+", "_", title.lower())[:60]
        external_id = f"hltv_{slug}_{unix_ts or 'unknown'}"

    return {
        "title": title,
        "event_at": unix_ts,
        "description": event_name or None,
        "url": url,
        "external_id": external_id,
    }
