"""ConversationHandler for interactive /add command."""

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src import config
from src import database as db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

# Top-level choice
CHOOSING_TYPE = 0

# Birthday flow states
BD_NAME = 10
BD_DATE = 11
BD_NOTES = 12

# Reminder flow states
REM_TITLE = 20
REM_WHEN = 21
REM_RECURRING = 22

# Context keys
_KEY = "add_data"


# ---------------------------------------------------------------------------
# Entry point: /add
# ---------------------------------------------------------------------------

def _type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Birthday", callback_data="type_birthday"),
            InlineKeyboardButton("Reminder", callback_data="type_reminder"),
        ],
        [InlineKeyboardButton("← Cancel", callback_data="add_cancel")],
    ])


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[_KEY] = {}
    await update.message.reply_text("What would you like to add?", reply_markup=_type_keyboard())
    return CHOOSING_TYPE


async def cmd_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point when the user taps '+ Add' from the inline menu."""
    query = update.callback_query
    await query.answer()
    context.user_data[_KEY] = {}
    await query.edit_message_text("What would you like to add?", reply_markup=_type_keyboard())
    return CHOOSING_TYPE


# ---------------------------------------------------------------------------
# Type selection callback
# ---------------------------------------------------------------------------

async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "add_cancel":
        await query.edit_message_text("Cancelled.")
        context.user_data.pop(_KEY, None)
        return ConversationHandler.END

    context.user_data[_KEY] = {}

    if query.data == "type_birthday":
        await query.edit_message_text("Enter the person's name:")
        return BD_NAME
    elif query.data == "type_reminder":
        await query.edit_message_text("What should I remind you about?")
        return REM_TITLE
    else:
        await query.edit_message_text("Unknown option. Use /add to start over.")
        return ConversationHandler.END


# ---------------------------------------------------------------------------
# Birthday flow
# ---------------------------------------------------------------------------

async def bd_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Name cannot be empty. Please enter a name:")
        return BD_NAME
    context.user_data[_KEY]["name"] = name
    await update.message.reply_text(
        "Enter their birthday (DD.MM or DD.MM.YYYY):"
    )
    return BD_DATE


async def bd_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    parsed = _parse_birthday_date(text)
    if parsed is None:
        await update.message.reply_text(
            "Could not parse the date. Use DD.MM or DD.MM.YYYY format (e.g. 25.03 or 25.03.1990):"
        )
        return BD_DATE

    context.user_data[_KEY]["month"] = parsed[0]
    context.user_data[_KEY]["day"] = parsed[1]
    await update.message.reply_text("Any notes? (send /skip to leave blank)")
    return BD_NOTES


async def bd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    notes: Optional[str] = None
    if text.lower() != "/skip" and text:
        notes = text

    data = context.user_data[_KEY]
    name = data["name"]
    month = data["month"]
    day = data["day"]

    from src.handlers.commands import _main_menu_keyboard
    try:
        bday_id = await db.add_birthday(
            config.DB_PATH, name=name, month=month, day=day, notes=notes,
        )
        text = (
            f"Birthday saved! [ID: {bday_id}]\n"
            f"<b>{html.escape(name)}</b> — {day:02d}.{month:02d}"
            + (f"\nNotes: {html.escape(notes)}" if notes else "")
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_main_menu_keyboard())
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save birthday: %s", exc)
        await update.message.reply_text("Failed to save birthday. Please try again.")

    context.user_data.pop(_KEY, None)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Reminder flow
# ---------------------------------------------------------------------------

async def rem_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Title cannot be empty. What should I remind you about?")
        return REM_TITLE
    context.user_data[_KEY]["title"] = title
    await update.message.reply_text(
        "When? Examples:\n"
        "- 15.06.2025 14:00\n"
        "- tomorrow 10:00\n"
        "- 2025-12-31 09:00"
    )
    return REM_WHEN


async def rem_when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    remind_dt = _parse_reminder_datetime(text)
    if remind_dt is None:
        await update.message.reply_text(
            "Could not parse the date/time. Try formats like:\n"
            "- 15.06.2025 14:00\n"
            "- tomorrow 10:00\n"
            "- 2025-12-31 09:00"
        )
        return REM_WHEN

    context.user_data[_KEY]["remind_at"] = remind_dt.isoformat()

    keyboard = [
        [
            InlineKeyboardButton("No", callback_data="rec_no"),
            InlineKeyboardButton("Daily", callback_data="rec_daily"),
        ],
        [
            InlineKeyboardButton("Weekly", callback_data="rec_weekly"),
            InlineKeyboardButton("Monthly", callback_data="rec_monthly"),
        ],
        [
            InlineKeyboardButton("Yearly", callback_data="rec_yearly"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Should this reminder recur?",
        reply_markup=reply_markup,
    )
    return REM_RECURRING


async def rem_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    recurring_map = {
        "rec_no": None,
        "rec_daily": "daily",
        "rec_weekly": "weekly",
        "rec_monthly": "monthly",
        "rec_yearly": "yearly",
    }
    recurring = recurring_map.get(data)

    stored = context.user_data[_KEY]
    title = stored["title"]
    remind_at = stored["remind_at"]

    try:
        rem_id = await db.add_reminder(
            config.DB_PATH,
            title=title,
            remind_at=remind_at,
            notes=stored.get("notes"),
            recurring=recurring,
        )
        tz = config.TIMEZONE
        try:
            dt = datetime.fromisoformat(remind_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_local = dt.astimezone(tz)
            date_str = dt_local.strftime("%a, %d %b %Y at %H:%M")
        except Exception:  # noqa: BLE001
            date_str = remind_at

        from src.handlers.commands import _main_menu_keyboard
        rec_str = f" (recurring: {recurring})" if recurring else ""
        await query.edit_message_text(
            f"Reminder saved! [ID: {rem_id}]\n"
            f"<b>{html.escape(title)}</b>\n"
            f"{html.escape(date_str)}{html.escape(rec_str)}",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save reminder: %s", exc)
        await query.edit_message_text("Failed to save reminder. Please try again.")

    context.user_data.pop(_KEY, None)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(_KEY, None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

def _parse_birthday_date(text: str) -> Optional[tuple[int, int]]:
    """Parse DD.MM or DD.MM.YYYY and return (month, day) or None."""
    text = text.strip()

    # DD.MM.YYYY
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        try:
            datetime(year=int(m.group(3)), month=month, day=day)
            return (month, day)
        except ValueError:
            return None

    # DD.MM
    m = re.match(r"^(\d{1,2})\.(\d{1,2})$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        try:
            # Validate the day/month combination
            datetime(year=datetime.now().year, month=month, day=day)
            return (month, day)
        except ValueError:
            return None

    return None


def _parse_reminder_datetime(text: str) -> Optional[datetime]:
    """Parse a human-friendly datetime string into a UTC-aware datetime."""
    text = text.strip()
    tz = config.TIMEZONE
    now_local = datetime.now(tz)

    # Try "tomorrow HH:MM"
    m = re.match(r"^tomorrow\s+(\d{1,2}):(\d{2})$", text, re.IGNORECASE)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        tomorrow = now_local.date() + timedelta(days=1)
        try:
            dt = tz.localize(datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute))
            return dt.astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            return None

    # Try "today HH:MM"
    m = re.match(r"^today\s+(\d{1,2}):(\d{2})$", text, re.IGNORECASE)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        today = now_local.date()
        try:
            dt = tz.localize(datetime(today.year, today.month, today.day, hour, minute))
            return dt.astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            return None

    # Try DD.MM.YYYY HH:MM
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})$", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
        try:
            dt = tz.localize(datetime(year, month, day, hour, minute))
            return dt.astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            return None

    # Try DD.MM.YYYY (no time — default to 09:00)
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = tz.localize(datetime(year, month, day, 9, 0))
            return dt.astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            return None

    # Try ISO: YYYY-MM-DD HH:MM or YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{1,2}):(\d{2}))?$", text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour = int(m.group(4)) if m.group(4) else 9
        minute = int(m.group(5)) if m.group(5) else 0
        try:
            dt = tz.localize(datetime(year, month, day, hour, minute))
            return dt.astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            return None

    # Fallback: try dateutil
    try:
        from dateutil import parser as du_parser

        dt = du_parser.parse(text, dayfirst=True)
        if dt.tzinfo is None:
            dt = tz.localize(dt)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        pass

    return None


# ---------------------------------------------------------------------------
# ConversationHandler factory
# ---------------------------------------------------------------------------

def add_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("add", cmd_add),
            CallbackQueryHandler(cmd_add_callback, pattern="^add_item$"),
        ],
        states={
            CHOOSING_TYPE: [
                CallbackQueryHandler(choose_type, pattern=r"^(type_|add_cancel)"),
            ],
            BD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bd_name),
            ],
            BD_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bd_date),
            ],
            BD_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bd_notes),
                CommandHandler("skip", bd_notes),
            ],
            REM_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rem_title),
            ],
            REM_WHEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rem_when),
            ],
            REM_RECURRING: [
                CallbackQueryHandler(rem_recurring, pattern=r"^rec_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_conversation",
        persistent=False,
    )
