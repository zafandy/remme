"""APScheduler jobs for the remme bot."""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src import config
from src import database as db

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)


def _tz():
    return config.TIMEZONE


# ---------------------------------------------------------------------------
# Job: daily digest
# ---------------------------------------------------------------------------

async def _send_daily_digest(app: "Application") -> None:
    """Send today's events plus anything due in the next 3 days."""
    from src.handlers.commands import build_upcoming_message

    try:
        text = await build_upcoming_message(days=3, include_past_today=True)
        if text.strip():
            await app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=text,
                parse_mode="Markdown",
            )
            logger.info("Daily digest sent")
        else:
            await app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text="No events coming up in the next 3 days.",
                parse_mode="Markdown",
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Daily digest failed: %s", exc)


# ---------------------------------------------------------------------------
# Job: reminder check (every 15 minutes)
# ---------------------------------------------------------------------------

async def _check_reminders(app: "Application") -> None:
    """Fire reminders whose remind_at falls within the next 15 minutes."""
    try:
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=15)

        reminders = await db.get_active_reminders(config.DB_PATH)
        for reminder in reminders:
            try:
                remind_at_str = reminder["remind_at"]
                remind_dt = datetime.fromisoformat(remind_at_str)
                if remind_dt.tzinfo is None:
                    remind_dt = remind_dt.replace(tzinfo=timezone.utc)

                if now <= remind_dt <= window_end:
                    text = _format_reminder_alert(reminder)
                    await app.bot.send_message(
                        chat_id=config.TELEGRAM_CHAT_ID,
                        text=text,
                        parse_mode="Markdown",
                    )
                    logger.info("Fired reminder id=%s: %s", reminder["id"], reminder["title"])

                    recurring = reminder.get("recurring")
                    if recurring:
                        await db.advance_recurring_reminder(
                            config.DB_PATH,
                            reminder["id"],
                            recurring,
                            remind_at_str,
                        )
                    else:
                        await db.deactivate_reminder(config.DB_PATH, reminder["id"])

            except Exception as exc:  # noqa: BLE001
                logger.error("Error processing reminder id=%s: %s", reminder.get("id"), exc)

    except Exception as exc:  # noqa: BLE001
        logger.error("Reminder check job failed: %s", exc)


def _format_reminder_alert(reminder: dict) -> str:
    title = reminder["title"]
    notes = reminder.get("notes") or ""
    recurring = reminder.get("recurring")

    lines = [f"*Reminder:* {title}"]
    if notes:
        lines.append(f"_{notes}_")
    if recurring:
        lines.append(f"_(Recurring: {recurring})_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Job: birthday check (every day at 08:00)
# ---------------------------------------------------------------------------

async def _check_birthdays(app: "Application") -> None:
    """Alert if any birthday is today or in exactly 3 days."""
    try:
        today_local = datetime.now(_tz()).date()
        birthdays = await db.get_birthdays(config.DB_PATH)

        alerts: list[str] = []
        for bday in birthdays:
            month = bday["month"]
            day = bday["day"]
            name = bday["name"]
            notes = bday.get("notes") or ""

            try:
                this_year = today_local.replace(month=month, day=day)
            except ValueError:
                continue  # e.g. Feb 29

            # Calculate days until birthday this year
            delta = (this_year - today_local).days
            if delta < 0:
                # Birthday already passed this year; compute for next year
                try:
                    next_year_bday = this_year.replace(year=today_local.year + 1)
                    delta = (next_year_bday - today_local).days
                except ValueError:
                    continue

            if delta == 0:
                msg = f"Today is *{name}*'s birthday!"
                if notes:
                    msg += f" _{notes}_"
                alerts.append(msg)
            elif delta == 3:
                msg = f"*{name}*'s birthday is in 3 days ({this_year.strftime('%d %b')})."
                if notes:
                    msg += f" _{notes}_"
                alerts.append(msg)

        if alerts:
            header = "*Birthday Alert*\n\n"
            text = header + "\n".join(alerts)
            await app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=text,
                parse_mode="Markdown",
            )
            logger.info("Birthday alerts sent: %d", len(alerts))

    except Exception as exc:  # noqa: BLE001
        logger.error("Birthday check job failed: %s", exc)


# ---------------------------------------------------------------------------
# Job: data refresh (every 6 hours)
# ---------------------------------------------------------------------------

async def _refresh_data(app: "Application") -> None:
    """Refresh HLTV, F1, and Hajime caches."""
    from src.scrapers.hltv import scrape_navi_matches
    from src.scrapers.f1 import fetch_f1_races
    from src.scrapers.hajime import fetch_hajime_releases

    logger.info("Starting scheduled data refresh...")

    # CS2 / HLTV
    try:
        cs2_events = await scrape_navi_matches()
        if cs2_events:
            await db.upsert_cache_events(config.DB_PATH, "cs2", cs2_events)
            logger.info("CS2 cache refreshed: %d events", len(cs2_events))
    except Exception as exc:  # noqa: BLE001
        logger.error("CS2 refresh failed: %s", exc)

    # F1
    try:
        f1_events = await fetch_f1_races()
        if f1_events:
            await db.upsert_cache_events(config.DB_PATH, "f1", f1_events)
            logger.info("F1 cache refreshed: %d events", len(f1_events))
    except Exception as exc:  # noqa: BLE001
        logger.error("F1 refresh failed: %s", exc)

    # Hajime
    try:
        hajime_events = await fetch_hajime_releases(config.HAJIME_CHANNEL_ID)
        if hajime_events:
            await db.upsert_cache_events(config.DB_PATH, "hajime", hajime_events)
            logger.info("Hajime cache refreshed: %d events", len(hajime_events))
    except Exception as exc:  # noqa: BLE001
        logger.error("Hajime refresh failed: %s", exc)

    logger.info("Scheduled data refresh complete")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_scheduler(app: "Application") -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=_tz())

    # Daily digest at 09:00 local time
    scheduler.add_job(
        _send_daily_digest,
        CronTrigger(hour=9, minute=0, timezone=_tz()),
        args=[app],
        id="daily_digest",
        replace_existing=True,
    )

    # Reminder check every 15 minutes
    scheduler.add_job(
        _check_reminders,
        IntervalTrigger(minutes=15),
        args=[app],
        id="reminder_check",
        replace_existing=True,
    )

    # Birthday check at 08:00 local time
    scheduler.add_job(
        _check_birthdays,
        CronTrigger(hour=8, minute=0, timezone=_tz()),
        args=[app],
        id="birthday_check",
        replace_existing=True,
    )

    # Data refresh every 6 hours
    scheduler.add_job(
        _refresh_data,
        IntervalTrigger(hours=6),
        args=[app],
        id="data_refresh",
        replace_existing=True,
    )

    return scheduler
