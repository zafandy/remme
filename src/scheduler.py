"""APScheduler jobs for the remme bot."""

import html
import logging
from collections import defaultdict
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
# Helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    return html.escape(str(text))


def _fmt_time(iso_str: str | None, tz) -> str:
    if not iso_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%H:%M")
    except (ValueError, TypeError):
        return iso_str


def _fmt_dt(iso_str: str | None, tz) -> str:
    if not iso_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%a, %d %b at %H:%M")
    except (ValueError, TypeError):
        return iso_str


def _is_today(iso_str: str, tz, today) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).date() == today
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Job 1: Morning digest + birthday alerts at 07:00
# ---------------------------------------------------------------------------

async def _morning_digest(app: "Application") -> None:
    try:
        tz = _tz()
        now = datetime.now(timezone.utc)
        today_local = datetime.now(tz).date()

        parts: list[str] = [
            f"<b>Good morning — {today_local.strftime('%A, %d %b %Y')}</b>"
        ]
        sections: list[str] = []

        # CS2 today
        cs2_today = [
            ev for ev in await db.get_cache_events(config.DB_PATH, "cs2")
            if ev.get("event_at") and _is_today(ev["event_at"], tz, today_local)
        ]
        if cs2_today:
            lines = ["<b>[ CS2 ]</b>"]
            for ev in cs2_today:
                desc = f" [{_e(ev['description'])}]" if ev.get("description") else ""
                lines.append(f"- {_e(ev['title'])}{desc}\n  {_fmt_time(ev['event_at'], tz)}")
            sections.append("\n".join(lines))

        # F1 today — grouped by GP
        f1_today = [
            ev for ev in await db.get_cache_events(config.DB_PATH, "f1")
            if ev.get("event_at") and _is_today(ev["event_at"], tz, today_local)
        ]
        if f1_today:
            gp_groups: dict[str, list] = defaultdict(list)
            for ev in f1_today:
                gp_groups[ev.get("description") or "F1"].append(ev)
            lines = ["<b>[ FORMULA 1 ]</b>"]
            for gp_name, sessions in gp_groups.items():
                lines.append(f"<b>{_e(gp_name)}</b>")
                for s in sessions:
                    title = s.get("title", "")
                    session_label = title.split(" — ", 1)[1] if " — " in title else title
                    lines.append(f"  {_e(session_label)}: {_fmt_time(s['event_at'], tz)}")
            sections.append("\n".join(lines))

        # Barcelona today
        barca_today = [
            ev for ev in await db.get_cache_events(config.DB_PATH, "barcelona")
            if ev.get("event_at") and _is_today(ev["event_at"], tz, today_local)
        ]
        if barca_today:
            lines = ["<b>[ BARCELONA ]</b>"]
            for ev in barca_today:
                desc = f" [{_e(ev['description'])}]" if ev.get("description") else ""
                lines.append(f"- {_e(ev['title'])}{desc}\n  {_fmt_time(ev['event_at'], tz)}")
            sections.append("\n".join(lines))

        # Reminders today
        rems_today = [
            r for r in await db.get_active_reminders(config.DB_PATH)
            if r.get("remind_at") and _is_today(r["remind_at"], tz, today_local)
        ]
        if rems_today:
            lines = ["<b>[ REMINDERS ]</b>"]
            for rem in rems_today:
                line = f"- {_e(rem['title'])}\n  {_fmt_time(rem['remind_at'], tz)}"
                if rem.get("notes"):
                    line += f"\n  <i>{_e(rem['notes'])}</i>"
                lines.append(line)
            sections.append("\n".join(lines))

        if sections:
            divider = "\n" + "─" * 28 + "\n"
            parts.append("\n\nToday's schedule:\n" + divider.join(sections))
        else:
            parts.append("\n\nNothing scheduled for today.")

        # Birthday alerts (today + 3 days)
        bday_alerts = await _build_birthday_alerts(today_local)
        if bday_alerts:
            parts.append("\n\n<b>[ BIRTHDAYS ]</b>\n" + "\n".join(bday_alerts))

        text = "".join(parts)
        await app.bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
        logger.info("Morning digest sent")

    except Exception as exc:
        logger.error("Morning digest failed: %s", exc)


async def _build_birthday_alerts(today) -> list[str]:
    alerts: list[str] = []
    for bday in await db.get_birthdays(config.DB_PATH):
        month, day = bday["month"], bday["day"]
        name = bday["name"]
        notes = bday.get("notes") or ""
        try:
            this_year = today.replace(month=month, day=day)
            delta = (this_year - today).days
            if delta < 0:
                this_year = this_year.replace(year=today.year + 1)
                delta = (this_year - today).days
        except ValueError:
            continue
        if delta == 0:
            msg = f"Today is <b>{_e(name)}</b>'s birthday!"
            if notes:
                msg += f" <i>{_e(notes)}</i>"
            alerts.append(msg)
        elif delta == 3:
            msg = f"<b>{_e(name)}</b>'s birthday in 3 days ({this_year.strftime('%d %b')})"
            if notes:
                msg += f" — <i>{_e(notes)}</i>"
            alerts.append(msg)
    return alerts


# ---------------------------------------------------------------------------
# Job 2: Event alerts every 5 minutes (1h before + at start for CS2/F1/Barcelona)
# ---------------------------------------------------------------------------

_ALERT_CATEGORIES = ("cs2", "f1", "barcelona")


async def _event_alerts(app: "Application") -> None:
    try:
        now = datetime.now(timezone.utc)

        for category in _ALERT_CATEGORIES:
            events = await db.get_cache_events(config.DB_PATH, category)
            for ev in events:
                ext_id = ev.get("external_id")
                event_at = ev.get("event_at")
                if not ext_id or not event_at:
                    continue

                try:
                    dt = datetime.fromisoformat(event_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

                minutes_until = (dt - now).total_seconds() / 60

                # 1 hour before: fire when 50–70 min away
                if 50 <= minutes_until <= 70:
                    if not await db.has_notification_sent(config.DB_PATH, ext_id, "1h_before"):
                        await _send_event_alert(app, ev, "1h_before")
                        await db.mark_notification_sent(config.DB_PATH, ext_id, "1h_before")

                # At start: fire when -5 to +10 min from start
                if -5 <= minutes_until <= 10:
                    if not await db.has_notification_sent(config.DB_PATH, ext_id, "start"):
                        await _send_event_alert(app, ev, "start")
                        await db.mark_notification_sent(config.DB_PATH, ext_id, "start")

    except Exception as exc:
        logger.error("Event alerts job failed: %s", exc)


async def _send_event_alert(app: "Application", ev: dict, notif_type: str) -> None:
    tz = _tz()
    title = _e(ev.get("title", "Unknown event"))
    desc = ev.get("description") or ""
    date_str = _fmt_dt(ev.get("event_at"), tz)

    if notif_type == "1h_before":
        header = f"Starts in 1 hour: <b>{title}</b>"
    else:
        header = f"Starting now: <b>{title}</b>"

    lines = [header, date_str]
    if desc:
        lines.append(_e(desc))

    await app.bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text="\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Event alert (%s) sent for: %s", notif_type, ev.get("title"))


# ---------------------------------------------------------------------------
# Job 3: Reminder check every 5 minutes
# ---------------------------------------------------------------------------

async def _check_reminders(app: "Application") -> None:
    try:
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=5)

        for reminder in await db.get_active_reminders(config.DB_PATH):
            try:
                remind_dt = datetime.fromisoformat(reminder["remind_at"])
                if remind_dt.tzinfo is None:
                    remind_dt = remind_dt.replace(tzinfo=timezone.utc)

                if now <= remind_dt <= window_end:
                    await _send_reminder_alert(app, reminder)

                    recurring = reminder.get("recurring")
                    if recurring:
                        await db.advance_recurring_reminder(
                            config.DB_PATH, reminder["id"], recurring, reminder["remind_at"]
                        )
                    else:
                        await db.deactivate_reminder(config.DB_PATH, reminder["id"])

            except Exception as exc:
                logger.error("Error processing reminder id=%s: %s", reminder.get("id"), exc)

    except Exception as exc:
        logger.error("Reminder check job failed: %s", exc)


async def _send_reminder_alert(app: "Application", reminder: dict) -> None:
    title = _e(reminder["title"])
    notes = reminder.get("notes") or ""
    recurring = reminder.get("recurring")

    lines = [f"<b>Reminder:</b> {title}"]
    if notes:
        lines.append(f"<i>{_e(notes)}</i>")
    if recurring:
        lines.append(f"<i>(Recurring: {recurring})</i>")

    await app.bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text="\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Fired reminder id=%s: %s", reminder["id"], reminder["title"])


# ---------------------------------------------------------------------------
# Job 4: Data refresh every 6 hours
# ---------------------------------------------------------------------------

async def _refresh_data(app: "Application") -> None:
    from src.scrapers.hltv import scrape_navi_matches
    from src.scrapers.f1 import fetch_f1_races
    from src.scrapers.hajime import fetch_hajime_releases
    from src.scrapers.barcelona import fetch_barcelona_matches

    logger.info("Starting scheduled data refresh...")

    for label, coro, category in [
        ("CS2", scrape_navi_matches(), "cs2"),
        ("F1", fetch_f1_races(), "f1"),
        ("Hajime", fetch_hajime_releases(config.HAJIME_CHANNEL_ID), "hajime"),
        ("Barcelona", fetch_barcelona_matches(config.BARCELONA_TEAM_ID), "barcelona"),
    ]:
        try:
            events = await coro
            if events:
                await db.upsert_cache_events(config.DB_PATH, category, events)
                logger.info("%s cache refreshed: %d events", label, len(events))
        except Exception as exc:
            logger.error("%s refresh failed: %s", label, exc)

    await db.cleanup_old_notifications(config.DB_PATH)
    logger.info("Scheduled data refresh complete")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_scheduler(app: "Application") -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=_tz())

    scheduler.add_job(
        _morning_digest,
        CronTrigger(hour=7, minute=0, timezone=_tz()),
        args=[app],
        id="morning_digest",
        replace_existing=True,
    )

    scheduler.add_job(
        _event_alerts,
        IntervalTrigger(minutes=5),
        args=[app],
        id="event_alerts",
        replace_existing=True,
    )

    scheduler.add_job(
        _check_reminders,
        IntervalTrigger(minutes=5),
        args=[app],
        id="reminder_check",
        replace_existing=True,
    )

    scheduler.add_job(
        _refresh_data,
        IntervalTrigger(hours=6),
        args=[app],
        id="data_refresh",
        replace_existing=True,
    )

    return scheduler
