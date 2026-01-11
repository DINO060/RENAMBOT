# utils/quota.py
from __future__ import annotations

import os
import datetime as dt
from zoneinfo import ZoneInfo
import aiosqlite

DB_PATH = os.getenv("QUOTA_DB_PATH", "quota.db")

async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS quotas (
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day)
        )
        """
    )
    await db.commit()

async def init_quota_db(db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await _ensure_schema(db)

def _today_str(tz_name: str) -> str:
    now = dt.datetime.now(ZoneInfo(tz_name))
    return now.strftime("%Y-%m-%d")

def _reset_time_str(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now = dt.datetime.now(tz)
    tomorrow = (now + dt.timedelta(days=1)).date()
    reset_dt = dt.datetime.combine(tomorrow, dt.time(0, 0), tzinfo=tz)
    return reset_dt.strftime("%H:%M %Z")

async def increment_if_under_limit(
    user_id: int,
    daily_limit: int,
    tz_name: str = "UTC",
    db_path: str = DB_PATH,
    is_admin: bool = False,
) -> tuple[bool, int, str, bool]:
    """
    Retourne (ok, remaining, reset_time_str, just_reached_limit)
    - ok=False si la limite est atteinte (aucune incrémentation)
    - remaining = nombre d'actions restantes aujourd'hui (0 si limite atteinte)
    - reset_time_str = heure locale de reset (ex: '00:00 UTC')
    - just_reached_limit=True si cette action vient d'atteindre la limite
    - is_admin=True pour bypass les quotas (illimité)
    """
    # Admins ont des quotas illimités
    if is_admin:
        return True, 999999, _reset_time_str(tz_name), False

    async with aiosqlite.connect(db_path) as db:
        await _ensure_schema(db)
        day = _today_str(tz_name)

        cur = await db.execute(
            "SELECT used FROM quotas WHERE user_id=? AND day=?", (user_id, day)
        )
        row = await cur.fetchone()
        await cur.close()

        used = int(row[0]) if row else 0

        if used >= daily_limit:
            return False, 0, _reset_time_str(tz_name), False

        new_used = used + 1
        if row is None:
            await db.execute(
                "INSERT INTO quotas (user_id, day, used) VALUES (?, ?, ?)",
                (user_id, day, new_used),
            )
        else:
            await db.execute(
                "UPDATE quotas SET used=? WHERE user_id=? AND day=?",
                (new_used, user_id, day),
            )
        await db.commit()

        remaining = max(daily_limit - new_used, 0)
        just_reached_limit = (new_used >= daily_limit)
        return True, remaining, _reset_time_str(tz_name), just_reached_limit
