"""aiosqlite database layer for remme bot."""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS birthdays (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    month       INTEGER NOT NULL,
    day         INTEGER NOT NULL,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    remind_at   TEXT    NOT NULL,   -- ISO datetime (UTC)
    notes       TEXT,
    recurring   TEXT,               -- NULL | 'daily' | 'weekly' | 'monthly' | 'yearly'
    active      INTEGER DEFAULT 1,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS event_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT    NOT NULL,   -- 'cs2' | 'f1' | 'hajime'
    title       TEXT    NOT NULL,
    event_at    TEXT,               -- ISO datetime or NULL
    description TEXT,
    url         TEXT,
    external_id TEXT    UNIQUE,
    fetched_at  TEXT    NOT NULL
);
"""


async def init_db(db_path: str) -> None:
    """Create tables if they don't exist."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("Database initialised at %s", db_path)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Birthdays
# ---------------------------------------------------------------------------

async def add_birthday(
    db_path: str,
    name: str,
    month: int,
    day: int,
    notes: Optional[str] = None,
) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "INSERT INTO birthdays (name, month, day, notes) VALUES (?, ?, ?, ?)",
            (name, month, day, notes),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_birthdays(db_path: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, month, day, notes FROM birthdays ORDER BY month, day"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_birthday(db_path: str, birthday_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM birthdays WHERE id = ?", (birthday_id,))
        await db.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

async def add_reminder(
    db_path: str,
    title: str,
    remind_at: str,
    notes: Optional[str] = None,
    recurring: Optional[str] = None,
) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """INSERT INTO reminders (title, remind_at, notes, recurring, active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (title, remind_at, notes, recurring, _now_iso()),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_active_reminders(db_path: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reminders WHERE active = 1 ORDER BY remind_at"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def deactivate_reminder(db_path: str, reminder_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,)
        )
        await db.commit()


async def advance_recurring_reminder(
    db_path: str, reminder_id: int, recurring: str, current_remind_at: str
) -> None:
    """Bump remind_at forward by the recurring interval."""
    from dateutil.relativedelta import relativedelta  # type: ignore

    dt = datetime.fromisoformat(current_remind_at)
    deltas = {
        "daily": relativedelta(days=1),
        "weekly": relativedelta(weeks=1),
        "monthly": relativedelta(months=1),
        "yearly": relativedelta(years=1),
    }
    delta = deltas.get(recurring)
    if delta is None:
        return
    new_dt = dt + delta
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE reminders SET remind_at = ? WHERE id = ?",
            (new_dt.isoformat(), reminder_id),
        )
        await db.commit()


async def delete_reminder(db_path: str, reminder_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await db.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Event cache
# ---------------------------------------------------------------------------

async def upsert_cache_events(
    db_path: str,
    category: str,
    events: list[dict[str, Any]],
) -> None:
    """Insert or replace events in the cache table."""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        # Remove stale entries for this category first
        await db.execute("DELETE FROM event_cache WHERE category = ?", (category,))
        for ev in events:
            await db.execute(
                """INSERT OR REPLACE INTO event_cache
                   (category, title, event_at, description, url, external_id, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    category,
                    ev.get("title", ""),
                    ev.get("event_at"),
                    ev.get("description"),
                    ev.get("url"),
                    ev.get("external_id"),
                    now,
                ),
            )
        await db.commit()


async def get_cache_events(
    db_path: str,
    category: str,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM event_cache WHERE category = ? ORDER BY event_at",
            (category,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]
