"""All bot command handlers — supports both slash commands and inline button callbacks."""

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src import config
from src import database as db

logger = logging.getLogger(__name__)

DATE_FMT = "%a, %d %b %Y at %H:%M"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_dt(iso_str: Optional[str], tz=None) -> str:
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


def _e(text: str) -> str:
    """HTML-escape external or user-provided content."""
    return html.escape(str(text))


def _divider() -> str:
    return "─" * 28


def _h(label: str) -> str:
    return f"<b>[ {label} ]</b>"


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Upcoming (7 days)", callback_data="upcoming"),
            InlineKeyboardButton("🗓 Today", callback_data="today"),
        ],
        [
            InlineKeyboardButton("🎮 CS2", callback_data="cs2"),
            InlineKeyboardButton("🏎️ Formula 1", callback_data="f1"),
        ],
        [
            InlineKeyboardButton("🎵 Music", callback_data="music"),
            InlineKeyboardButton("🎂 Birthdays", callback_data="birthdays"),
        ],
        [
            InlineKeyboardButton("⚽ Barcelona", callback_data="barcelona"),
            InlineKeyboardButton("📌 Reminders", callback_data="reminders"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh data", callback_data="refresh"),
            InlineKeyboardButton("➕ Add", callback_data="add_item"),
        ],
    ])


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Menu", callback_data="menu")]
    ])


# ---------------------------------------------------------------------------
# Unified reply helper — works for both /commands and button taps
# ---------------------------------------------------------------------------

async def _reply(
    update: Update,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# /start + menu callback
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, "🔔 <b>remme</b> — your personal reminder bot", keyboard=_main_menu_keyboard())


# ---------------------------------------------------------------------------
# Content builders (pure async functions, no Update dependency)
# ---------------------------------------------------------------------------

async def _build_cs2_text() -> str:
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
        return "No upcoming NaVi matches cached.\nTap <b>Refresh data</b> to update."

    lines = [_h("🎮 CS2") + " — NaVi upcoming matches\n"]
    for ev in upcoming:
        title = _e(ev.get("title", "Unknown match"))
        date_str = _e(_fmt_dt(ev.get("event_at"), tz))
        url = ev.get("url") or ""
        line = f"- {title}\n  {date_str}"
        if url:
            line += f"\n  {_e(url)}"
        lines.append(line)

    return "\n\n".join(lines)


async def _build_f1_text() -> str:
    from collections import defaultdict
    tz = config.TIMEZONE
    events = await db.get_cache_events(config.DB_PATH, "f1")
    now = datetime.now(timezone.utc)

    upcoming = sorted(
        [ev for ev in events if _is_future(ev.get("event_at", ""), now)],
        key=lambda e: e.get("event_at") or "",
    )

    if not upcoming:
        return "No upcoming F1 sessions cached.\nTap <b>Refresh data</b> to update."

    groups: dict[str, list] = defaultdict(list)
    for ev in upcoming:
        groups[ev.get("description") or "Unknown GP"].append(ev)

    sorted_groups = sorted(groups.items(), key=lambda g: g[1][0].get("event_at") or "")[:5]

    parts = [_h("🏎️ FORMULA 1") + "\n"]
    sep = "─" * 34

    for i, (gp_name, sessions) in enumerate(sorted_groups):
        if i > 0:
            parts.append(sep)
        parts.append(f"<b>{_e(gp_name)}</b>")

        rows: list[str] = []
        for s in sessions:
            raw_title = s.get("title", "")
            label = raw_title.split(" — ", 1)[1] if " — " in raw_title else raw_title
            event_at = s.get("event_at")
            if event_at:
                try:
                    dt = datetime.fromisoformat(event_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_local = dt.astimezone(tz)
                    date_col = dt_local.strftime("%a %d %b")
                    time_col = dt_local.strftime("%H:%M")
                except (ValueError, TypeError):
                    date_col = time_col = "TBD"
            else:
                date_col = time_col = "TBD"
            rows.append(f"{label:<16}{date_col:<13}{time_col}")

        parts.append("<pre>" + "\n".join(rows) + "</pre>")

    return "\n".join(parts)


async def _build_music_text() -> str:
    tz = config.TIMEZONE
    events = await db.get_cache_events(config.DB_PATH, "hajime")

    if not events:
        return "No Hajime releases cached.\nTap <b>Refresh data</b> to update."

    sorted_events = sorted(events, key=lambda e: e.get("event_at") or "", reverse=True)[:5]

    lines = [_h("🎵 MUSIC") + " — latest Hajime releases\n"]
    for ev in sorted_events:
        title = _e(ev.get("title", "Unknown release"))
        date_str = _e(_fmt_dt(ev.get("event_at"), tz))
        url = ev.get("url") or ""
        line = f"- <b>{title}</b>\n  {date_str}"
        if url:
            line += f"\n  {_e(url)}"
        lines.append(line)

    return "\n\n".join(lines)


async def _build_birthdays_text() -> str:
    birthdays = await db.get_birthdays(config.DB_PATH)
    if not birthdays:
        return "No birthdays saved.\nTap <b>+ Add</b> to add one."

    tz = config.TIMEZONE
    today_local = datetime.now(tz).date()

    lines = [_h("🎂 BIRTHDAYS") + "\n"]
    for bday in birthdays:
        month, day = bday["month"], bday["day"]
        name = _e(bday["name"])
        notes = bday.get("notes") or ""
        bday_id = bday["id"]

        try:
            this_year = today_local.replace(month=month, day=day)
            delta = (this_year - today_local).days
            if delta < 0:
                delta = (this_year.replace(year=today_local.year + 1) - today_local).days
        except ValueError:
            delta = -1

        if delta == 0:
            annotation = " — today!"
        elif delta > 0:
            annotation = f" — in {delta} days"
        else:
            annotation = ""

        line = f"[{bday_id}] <b>{name}</b> ({day:02d}.{month:02d}){_e(annotation)}"
        if notes:
            line += f"\n  <i>{_e(notes)}</i>"
        lines.append(line)

    return "\n\n".join(lines)


async def _build_reminders_text() -> str:
    reminders = await db.get_active_reminders(config.DB_PATH)
    if not reminders:
        return "No active reminders.\nTap <b>+ Add</b> to create one."

    tz = config.TIMEZONE
    lines = [_h("📌 REMINDERS") + "\n"]
    for rem in reminders:
        title = _e(rem["title"])
        notes = rem.get("notes") or ""
        recurring = rem.get("recurring") or ""
        date_str = _e(_fmt_dt(rem["remind_at"], tz))

        line = f"[{rem['id']}] <b>{title}</b>\n  {date_str}"
        if recurring:
            line += f" (recurring: {recurring})"
        if notes:
            line += f"\n  <i>{_e(notes)}</i>"
        lines.append(line)

    return "\n\n".join(lines)


async def _build_barcelona_text() -> str:
    tz = config.TIMEZONE
    events = await db.get_cache_events(config.DB_PATH, "barcelona")
    now = datetime.now(timezone.utc)

    upcoming = sorted(
        [ev for ev in events if _is_future(ev.get("event_at", ""), now)],
        key=lambda e: e.get("event_at") or "",
    )[:5]

    if not upcoming:
        return "No upcoming Barcelona matches cached.\nTap <b>Refresh data</b> to update."

    lines = [_h("⚽ BARCELONA") + " — FC Barcelona upcoming matches\n"]
    for ev in upcoming:
        title = _e(ev.get("title", "Unknown match"))
        desc = _e(ev.get("description") or "")
        date_str = _e(_fmt_dt(ev.get("event_at"), tz))
        line = f"- <b>{title}</b>"
        if desc:
            line += f"\n  {desc}"
        line += f"\n  {date_str}"
        lines.append(line)

    return "\n\n".join(lines)


async def build_upcoming_message(days: int = 7) -> str:
    tz = config.TIMEZONE
    now = datetime.now(timezone.utc)
    now_local = datetime.now(tz)
    if days == 0:
        # End of today in local timezone
        tomorrow = (now_local + timedelta(days=1)).date()
        cutoff = tz.localize(
            datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)
        ).astimezone(timezone.utc)
    else:
        cutoff = now + timedelta(days=days)
    sections: list[str] = []

    # CS2
    cs2_lines: list[str] = []
    for ev in await db.get_cache_events(config.DB_PATH, "cs2"):
        if ev.get("event_at") and not _in_window(ev["event_at"], now, cutoff):
            continue
        title = _e(ev.get("title", "Unknown match"))
        date_str = _e(_fmt_dt(ev.get("event_at"), tz))
        url = ev.get("url") or ""
        line = f"- {title}\n  {date_str}"
        if url:
            line += f"\n  {_e(url)}"
        cs2_lines.append(line)
    if cs2_lines:
        sections.append(_h("🎮 CS2") + "\n" + "\n\n".join(cs2_lines))

    # F1
    f1_lines: list[str] = []
    for ev in await db.get_cache_events(config.DB_PATH, "f1"):
        if ev.get("event_at") and not _in_window(ev["event_at"], now, cutoff):
            continue
        title = _e(ev.get("title", "Unknown race"))
        desc = _e(ev.get("description") or "")
        date_str = _e(_fmt_dt(ev.get("event_at"), tz))
        line = f"- {title}"
        if desc:
            line += f" ({desc})"
        line += f"\n  {date_str}"
        f1_lines.append(line)
    if f1_lines:
        sections.append(_h("🏎️ FORMULA 1") + "\n" + "\n\n".join(f1_lines))

    # Barcelona
    barca_lines: list[str] = []
    for ev in await db.get_cache_events(config.DB_PATH, "barcelona"):
        if ev.get("event_at") and not _in_window(ev["event_at"], now, cutoff):
            continue
        title = _e(ev.get("title", "Unknown match"))
        desc = _e(ev.get("description") or "")
        date_str = _e(_fmt_dt(ev.get("event_at"), tz))
        line = f"- {title}"
        if desc:
            line += f" ({desc})"
        line += f"\n  {date_str}"
        barca_lines.append(line)
    if barca_lines:
        sections.append(_h("⚽ BARCELONA") + "\n" + "\n\n".join(barca_lines))

    # Birthdays
    today_local = now_local.date()
    bday_lines: list[str] = []
    for bday in await db.get_birthdays(config.DB_PATH):
        month, day = bday["month"], bday["day"]
        name = _e(bday["name"])
        notes = bday.get("notes") or ""
        try:
            this_year = today_local.replace(month=month, day=day)
            delta = (this_year - today_local).days
            if delta < 0:
                delta = (this_year.replace(year=today_local.year + 1) - today_local).days
        except ValueError:
            continue
        if not (0 <= delta <= days):
            continue
        label = "today!" if delta == 0 else ("tomorrow" if delta == 1 else f"in {delta} days")
        line = f"- <b>{name}</b> — {this_year.strftime('%d %b')} ({label})"
        if notes:
            line += f"\n  <i>{_e(notes)}</i>"
        bday_lines.append(line)
    if bday_lines:
        sections.append(_h("🎂 BIRTHDAYS") + "\n" + "\n".join(bday_lines))

    # Reminders
    rem_lines: list[str] = []
    for rem in await db.get_active_reminders(config.DB_PATH):
        try:
            rem_dt = datetime.fromisoformat(rem["remind_at"])
            if rem_dt.tzinfo is None:
                rem_dt = rem_dt.replace(tzinfo=timezone.utc)
            if not (now <= rem_dt <= cutoff):
                continue
        except (ValueError, TypeError):
            continue
        title = _e(rem["title"])
        notes = rem.get("notes") or ""
        recurring = rem.get("recurring") or ""
        date_str = _e(_fmt_dt(rem["remind_at"], tz))
        line = f"- <b>{title}</b>\n  {date_str}"
        if recurring:
            line += f" (recurring: {recurring})"
        if notes:
            line += f"\n  <i>{_e(notes)}</i>"
        rem_lines.append(line)
    if rem_lines:
        sections.append(_h("📌 REMINDERS") + "\n" + "\n\n".join(rem_lines))

    if not sections:
        return ""
    return f"\n{_divider()}\n".join(sections)


# ---------------------------------------------------------------------------
# Datetime window helpers
# ---------------------------------------------------------------------------

def _is_future(iso_str: str, now: datetime) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= now
    except (ValueError, TypeError):
        return True


def _in_window(iso_str: str, now: datetime, cutoff: datetime) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return now <= dt <= cutoff
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Command / callback handlers
# ---------------------------------------------------------------------------

async def cmd_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await build_upcoming_message(days=7)
    await _reply(update, text or "No events in the next 7 days.", keyboard=_back_keyboard())


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await build_upcoming_message(days=0)
    await _reply(update, text or "Nothing scheduled for today.", keyboard=_back_keyboard())


async def cmd_cs2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, await _build_cs2_text(), keyboard=_back_keyboard())


async def cmd_f1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, await _build_f1_text(), keyboard=_back_keyboard())


async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, await _build_music_text(), keyboard=_back_keyboard())


async def cmd_barcelona(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, await _build_barcelona_text(), keyboard=_back_keyboard())


async def cmd_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, await _build_birthdays_text(), keyboard=_back_keyboard())


async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, await _build_reminders_text(), keyboard=_back_keyboard())


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(
            update,
            "Usage: /delete &lt;id&gt;\n"
            "Use /birthdays or /reminders to find the ID.",
            keyboard=_back_keyboard(),
        )
        return

    try:
        item_id = int(context.args[0])
    except ValueError:
        await _reply(update, "ID must be an integer.", keyboard=_back_keyboard())
        return

    if await db.delete_reminder(config.DB_PATH, item_id):
        await _reply(update, f"Reminder [{item_id}] deleted.", keyboard=_back_keyboard())
        return
    if await db.delete_birthday(config.DB_PATH, item_id):
        await _reply(update, f"Birthday [{item_id}] deleted.", keyboard=_back_keyboard())
        return

    await _reply(update, f"No item with ID {item_id} found.", keyboard=_back_keyboard())


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Acknowledge immediately, then edit with results when done
    await _reply(update, "Refreshing data, please wait...")

    from src.scrapers.hltv import scrape_navi_matches
    from src.scrapers.f1 import fetch_f1_races
    from src.scrapers.hajime import fetch_hajime_releases
    from src import database as db_module

    results: list[str] = []

    try:
        events = await scrape_navi_matches()
        if events:
            await db_module.upsert_cache_events(config.DB_PATH, "cs2", events)
            results.append(f"CS2: {len(events)} matches cached")
        else:
            results.append("CS2: data unavailable (HLTV may be blocking)")
    except Exception as exc:
        logger.error("CS2 refresh error: %s", exc)
        results.append("CS2: refresh failed")

    try:
        events = await fetch_f1_races()
        if events:
            await db_module.upsert_cache_events(config.DB_PATH, "f1", events)
            results.append(f"F1: {len(events)} races cached")
        else:
            results.append("F1: no upcoming races found")
    except Exception as exc:
        logger.error("F1 refresh error: %s", exc)
        results.append("F1: refresh failed")

    try:
        events = await fetch_hajime_releases(config.HAJIME_CHANNEL_ID)
        if events:
            await db_module.upsert_cache_events(config.DB_PATH, "hajime", events)
            results.append(f"Music: {len(events)} releases cached")
        else:
            results.append("Music: no releases found")
    except Exception as exc:
        logger.error("Hajime refresh error: %s", exc)
        results.append("Music: refresh failed")

    # Barcelona
    try:
        from src.scrapers.barcelona import fetch_barcelona_matches
        events = await fetch_barcelona_matches(config.BARCELONA_TEAM_ID)
        if events:
            await db_module.upsert_cache_events(config.DB_PATH, "barcelona", events)
            results.append(f"Barcelona: {len(events)} matches cached")
        else:
            results.append("Barcelona: no upcoming matches found")
    except Exception as exc:
        logger.error("Barcelona refresh error: %s", exc)
        results.append("Barcelona: refresh failed")

    summary = "<b>Refresh complete:</b>\n" + "\n".join(f"- {_e(r)}" for r in results)

    query = update.callback_query
    if query:
        await query.edit_message_text(summary, parse_mode=ParseMode.HTML, reply_markup=_back_keyboard())
    else:
        await update.message.reply_text(summary, parse_mode=ParseMode.HTML, reply_markup=_back_keyboard())
