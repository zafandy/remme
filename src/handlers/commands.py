"""All bot command handlers."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from src import config
from src import database as db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

DATE_FMT = "%a, %d %b %Y at %H:%M"


def _fmt_dt(iso_str: Optional[str], tz=None) -> str:
    """Format an ISO datetime string for display."""
    if not iso_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if tz is not None:
            dt = dt.astimezone(tz)
        return dt.strftime(DATE_FMT)
    except (ValueError, TypeError):
        return iso_str


def _escape_md(text: str) -> str:
    """Escape special Markdown characters (v1 / legacy mode)."""
    # Only escape characters that break Markdown v1 formatting
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def _divider() -> str:
    return "─" * 28


def _section_header(label: str) -> str:
    return f"*[ {label} ]*"


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*remme* — your personal reminder bot\n\n"
        "Commands:\n"
        "/upcoming — events in the next 7 days\n"
        "/today — events today\n"
        "/cs2 — upcoming NaVi matches\n"
        "/f1 — upcoming F1 races\n"
        "/music — latest Hajime releases\n"
        "/birthdays — birthday list\n"
        "/reminders — active reminders\n"
        "/add — add a birthday or reminder\n"
        "/delete <id> — delete a reminder or birthday\n"
        "/refresh — force-refresh scraped data\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /upcoming
# ---------------------------------------------------------------------------

async def build_upcoming_message(days: int = 7, include_past_today: bool = False) -> str:
    """Build a formatted message of events in the next `days` days."""
    tz = config.TIMEZONE
    now = datetime.now(timezone.utc)
    now_local = datetime.now(tz)
    cutoff = now + timedelta(days=days)

    sections: list[str] = []

    # --- CS2 ---
    cs2_events = await db.get_cache_events(config.DB_PATH, "cs2")
    cs2_lines: list[str] = []
    for ev in cs2_events:
        if ev.get("event_at"):
            try:
                dt = datetime.fromisoformat(ev["event_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now or dt > cutoff:
                    continue
            except ValueError:
                pass
        title = ev.get("title", "Unknown match")
        date_str = _fmt_dt(ev.get("event_at"), tz)
        url = ev.get("url") or ""
        line = f"- {title}\n  {date_str}"
        if url:
            line += f"\n  {url}"
        cs2_lines.append(line)

    if cs2_lines:
        block = _section_header("CS2") + "\n" + "\n\n".join(cs2_lines)
        sections.append(block)

    # --- F1 ---
    f1_events = await db.get_cache_events(config.DB_PATH, "f1")
    f1_lines: list[str] = []
    for ev in f1_events:
        if ev.get("event_at"):
            try:
                dt = datetime.fromisoformat(ev["event_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now or dt > cutoff:
                    continue
            except ValueError:
                pass
        title = ev.get("title", "Unknown race")
        desc = ev.get("description") or ""
        date_str = _fmt_dt(ev.get("event_at"), tz)
        line = f"- {title}"
        if desc:
            line += f" ({desc})"
        line += f"\n  {date_str}"
        f1_lines.append(line)

    if f1_lines:
        block = _section_header("FORMULA 1") + "\n" + "\n\n".join(f1_lines)
        sections.append(block)

    # --- Birthdays ---
    today_local = now_local.date()
    bday_lines: list[str] = []
    birthdays = await db.get_birthdays(config.DB_PATH)
    for bday in birthdays:
        month = bday["month"]
        day = bday["day"]
        name = bday["name"]
        notes = bday.get("notes") or ""
        try:
            this_year_bday = today_local.replace(month=month, day=day)
        except ValueError:
            continue
        delta = (this_year_bday - today_local).days
        if delta < 0:
            try:
                next_year_bday = this_year_bday.replace(year=today_local.year + 1)
                delta = (next_year_bday - today_local).days
                bday_date = next_year_bday
            except ValueError:
                continue
        else:
            bday_date = this_year_bday

        if 0 <= delta <= days:
            if delta == 0:
                label = "today!"
            elif delta == 1:
                label = "tomorrow"
            else:
                label = f"in {delta} days"
            line = f"- *{name}* — {bday_date.strftime('%d %b')} ({label})"
            if notes:
                line += f"\n  _{notes}_"
            bday_lines.append(line)

    if bday_lines:
        block = _section_header("BIRTHDAYS") + "\n" + "\n".join(bday_lines)
        sections.append(block)

    # --- Custom Reminders ---
    reminder_lines: list[str] = []
    reminders = await db.get_active_reminders(config.DB_PATH)
    for rem in reminders:
        try:
            rem_dt = datetime.fromisoformat(rem["remind_at"])
            if rem_dt.tzinfo is None:
                rem_dt = rem_dt.replace(tzinfo=timezone.utc)
            if rem_dt < now or rem_dt > cutoff:
                continue
        except (ValueError, TypeError):
            continue
        title = rem["title"]
        notes = rem.get("notes") or ""
        recurring = rem.get("recurring") or ""
        date_str = _fmt_dt(rem["remind_at"], tz)
        line = f"- *{title}*\n  {date_str}"
        if recurring:
            line += f" (recurring: {recurring})"
        if notes:
            line += f"\n  _{notes}_"
        reminder_lines.append(line)

    if reminder_lines:
        block = _section_header("REMINDERS") + "\n" + "\n\n".join(reminder_lines)
        sections.append(block)

    if not sections:
        return ""

    divider = f"\n{_divider()}\n"
    return divider.join(sections)


async def cmd_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await build_upcoming_message(days=7)
    if not text.strip():
        await update.message.reply_text("No events in the next 7 days.")
        return
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /today
# ---------------------------------------------------------------------------

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await build_upcoming_message(days=0)
    if not text.strip():
        await update.message.reply_text("Nothing scheduled for today.")
        return
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /cs2
# ---------------------------------------------------------------------------

async def cmd_cs2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = config.TIMEZONE
    events = await db.get_cache_events(config.DB_PATH, "cs2")
    now = datetime.now(timezone.utc)

    upcoming = []
    for ev in events:
        if ev.get("event_at"):
            try:
                dt = datetime.fromisoformat(ev["event_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now:
                    continue
            except ValueError:
                pass
        upcoming.append(ev)

    if not upcoming:
        await update.message.reply_text(
            "No upcoming NaVi matches cached. Try /refresh to update.",
        )
        return

    lines = [_section_header("CS2") + " — NaVi upcoming matches\n"]
    for ev in upcoming:
        title = ev.get("title", "Unknown match")
        date_str = _fmt_dt(ev.get("event_at"), tz)
        url = ev.get("url") or ""
        line = f"- {title}\n  {date_str}"
        if url:
            line += f"\n  {url}"
        lines.append(line)

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /f1
# ---------------------------------------------------------------------------

async def cmd_f1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = config.TIMEZONE
    events = await db.get_cache_events(config.DB_PATH, "f1")
    now = datetime.now(timezone.utc)

    upcoming = []
    for ev in events:
        if ev.get("event_at"):
            try:
                dt = datetime.fromisoformat(ev["event_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now:
                    continue
            except ValueError:
                pass
        upcoming.append(ev)

    # Show next 3 races
    upcoming = upcoming[:3]

    if not upcoming:
        await update.message.reply_text(
            "No upcoming F1 races cached. Try /refresh to update.",
        )
        return

    lines = [_section_header("FORMULA 1") + " — next races\n"]
    for ev in upcoming:
        title = ev.get("title", "Unknown race")
        desc = ev.get("description") or ""
        date_str = _fmt_dt(ev.get("event_at"), tz)
        url = ev.get("url") or ""
        line = f"- *{title}*"
        if desc:
            line += f"\n  {desc}"
        line += f"\n  {date_str}"
        if url:
            line += f"\n  {url}"
        lines.append(line)

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /music
# ---------------------------------------------------------------------------

async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = config.TIMEZONE
    events = await db.get_cache_events(config.DB_PATH, "hajime")

    if not events:
        await update.message.reply_text(
            "No Hajime releases cached. Try /refresh to update.",
        )
        return

    # Latest 5, most recent first
    sorted_events = sorted(
        events,
        key=lambda e: e.get("event_at") or "",
        reverse=True,
    )[:5]

    lines = [_section_header("MUSIC") + " — latest Hajime releases\n"]
    for ev in sorted_events:
        title = ev.get("title", "Unknown release")
        date_str = _fmt_dt(ev.get("event_at"), tz)
        url = ev.get("url") or ""
        line = f"- *{title}*\n  {date_str}"
        if url:
            line += f"\n  {url}"
        lines.append(line)

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /birthdays
# ---------------------------------------------------------------------------

async def cmd_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    birthdays = await db.get_birthdays(config.DB_PATH)
    if not birthdays:
        await update.message.reply_text("No birthdays saved. Use /add to add one.")
        return

    tz = config.TIMEZONE
    today_local = datetime.now(tz).date()

    lines = [_section_header("BIRTHDAYS") + "\n"]
    for bday in birthdays:
        month = bday["month"]
        day = bday["day"]
        name = bday["name"]
        notes = bday.get("notes") or ""
        bday_id = bday["id"]

        date_label = f"{day:02d}.{month:02d}"
        try:
            this_year_bday = today_local.replace(month=month, day=day)
            delta = (this_year_bday - today_local).days
            if delta < 0:
                next_year_bday = this_year_bday.replace(year=today_local.year + 1)
                delta = (next_year_bday - today_local).days
        except ValueError:
            delta = -1

        if delta == 0:
            upcoming = " — today!"
        elif delta > 0:
            upcoming = f" — in {delta} days"
        else:
            upcoming = ""

        line = f"[{bday_id}] *{name}* ({date_label}){upcoming}"
        if notes:
            line += f"\n  _{notes}_"
        lines.append(line)

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /reminders
# ---------------------------------------------------------------------------

async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reminders = await db.get_active_reminders(config.DB_PATH)
    if not reminders:
        await update.message.reply_text("No active reminders. Use /add to create one.")
        return

    tz = config.TIMEZONE
    lines = [_section_header("REMINDERS") + "\n"]
    for rem in reminders:
        rem_id = rem["id"]
        title = rem["title"]
        notes = rem.get("notes") or ""
        recurring = rem.get("recurring") or ""
        date_str = _fmt_dt(rem["remind_at"], tz)

        line = f"[{rem_id}] *{title}*\n  {date_str}"
        if recurring:
            line += f" (recurring: {recurring})"
        if notes:
            line += f"\n  _{notes}_"
        lines.append(line)

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /delete <id>\n"
            "Use /birthdays or /reminders to find the ID."
        )
        return

    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID must be an integer.")
        return

    # Try deleting from reminders first, then birthdays
    deleted = await db.delete_reminder(config.DB_PATH, item_id)
    if deleted:
        await update.message.reply_text(f"Reminder [{item_id}] deleted.")
        return

    deleted = await db.delete_birthday(config.DB_PATH, item_id)
    if deleted:
        await update.message.reply_text(f"Birthday [{item_id}] deleted.")
        return

    await update.message.reply_text(
        f"No reminder or birthday with ID {item_id} found."
    )


# ---------------------------------------------------------------------------
# /refresh
# ---------------------------------------------------------------------------

async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Refreshing data... please wait.")

    from src.scrapers.hltv import scrape_navi_matches
    from src.scrapers.f1 import fetch_f1_races
    from src.scrapers.hajime import fetch_hajime_releases
    from src import database as db_module

    results: list[str] = []

    # CS2
    try:
        events = await scrape_navi_matches()
        if events:
            await db_module.upsert_cache_events(config.DB_PATH, "cs2", events)
            results.append(f"CS2: {len(events)} matches cached")
        else:
            results.append("CS2: data unavailable — try again later")
    except Exception as exc:  # noqa: BLE001
        logger.error("CS2 refresh error: %s", exc)
        results.append("CS2: refresh failed")

    # F1
    try:
        events = await fetch_f1_races()
        if events:
            await db_module.upsert_cache_events(config.DB_PATH, "f1", events)
            results.append(f"F1: {len(events)} races cached")
        else:
            results.append("F1: no upcoming races found")
    except Exception as exc:  # noqa: BLE001
        logger.error("F1 refresh error: %s", exc)
        results.append("F1: refresh failed")

    # Hajime
    try:
        events = await fetch_hajime_releases(config.HAJIME_CHANNEL_ID)
        if events:
            await db_module.upsert_cache_events(config.DB_PATH, "hajime", events)
            results.append(f"Music: {len(events)} releases cached")
        else:
            results.append("Music: no releases found")
    except Exception as exc:  # noqa: BLE001
        logger.error("Hajime refresh error: %s", exc)
        results.append("Music: refresh failed")

    summary = "*Refresh complete:*\n" + "\n".join(f"- {r}" for r in results)
    await update.message.reply_text(summary, parse_mode="Markdown")
