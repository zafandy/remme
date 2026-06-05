"""YouTube RSS feed scraper for Hajime label channel."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import feedparser

logger = logging.getLogger(__name__)

_YT_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_MAX_ENTRIES = 5


async def fetch_hajime_releases(channel_id: str) -> list[dict[str, Any]]:
    """Fetch the latest videos from the Hajime label YouTube channel.

    Uses feedparser (synchronous under the hood) in a thread executor.
    Returns the last _MAX_ENTRIES videos as event dicts.
    """
    if not channel_id:
        logger.warning("Hajime channel ID is not configured; skipping fetch")
        return []

    url = _YT_RSS_URL.format(channel_id=channel_id)

    try:
        import asyncio

        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hajime RSS fetch failed: %s", exc)
        return []

    if feed.bozo and not feed.entries:
        logger.warning(
            "Hajime RSS feed parse error: %s", feed.get("bozo_exception", "unknown")
        )
        return []

    events: list[dict[str, Any]] = []
    for entry in feed.entries[:_MAX_ENTRIES]:
        ev = _entry_to_event(entry)
        if ev:
            events.append(ev)

    logger.info("Hajime: fetched %d latest releases", len(events))
    return events


def _entry_to_event(entry: Any) -> Optional[dict[str, Any]]:
    """Convert a feedparser entry to our event dict."""
    try:
        title: str = entry.get("title", "Unknown Release")
        link: str = entry.get("link", "")
        video_id: str = entry.get("yt_videoid", "")
        external_id = f"yt_{video_id}" if video_id else None

        # Published date
        event_at: Optional[str] = None
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            try:
                dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                event_at = dt.isoformat()
            except (ValueError, TypeError):
                pass

        if not event_at:
            published = entry.get("published", "")
            if published:
                try:
                    from dateutil import parser as du_parser

                    dt = du_parser.parse(published)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    event_at = dt.isoformat()
                except Exception:  # noqa: BLE001
                    pass

        return {
            "title": title,
            "event_at": event_at,
            "description": "New release on Hajime label",
            "url": link or None,
            "external_id": external_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not parse Hajime entry: %s", exc)
        return None
