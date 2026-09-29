"""BLOCKORA_TRADE v3 — market session handling (Asia/Kolkata)."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def is_market_open(now: datetime | None = None, open_t: str = "09:15",
                   close_t: str = "15:30", days: tuple[int, ...] = (0, 1, 2, 3, 4)) -> bool:
    local = now_ist(now)
    if local.weekday() not in days:
        return False
    o = time(*map(int, open_t.split(":")))
    c = time(*map(int, close_t.split(":")))
    return o <= local.time() <= c


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
