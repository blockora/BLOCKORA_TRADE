"""Single IST/UTC datetime policy for BLOCKORA_TRADE.

Live defect this fixes: subtracting an exchange expiry (parsed from a
date-only string, therefore NAIVE) from the current time (which
ConfigManager.now() returns as timezone-AWARE) raises

    TypeError: can't subtract offset-naive and offset-aware datetimes

and that exception was being swallowed, so option Greeks silently never
attached for any live cycle.

Policy
------
* Internally every datetime is timezone-AWARE and expressed in IST.
* Naive datetimes coming from a broker or an exchange are assumed to be
  IST (NSE publishes IST), not UTC. That assumption is applied in exactly
  one place, ist(), so it can be audited and changed without hunting.
* Exchanges quote IST wall-clock, so an expiry date string such as
  "29SEP2026" is the IST trading session date. It is anchored to the IST
  midnight, not to the host's local midnight.
* to_utc() exists for storage/comparison but is never needed to display a
  market timestamp in IST.

Every conversion is explicit. Nothing here silently returns a naive value.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

IST_NAME = "Asia/Kolkata"
_UTC = timezone.utc


def _tz():
    """IST tzinfo. pytz is already a dependency; ZoneInfo is the fallback."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(IST_NAME)
    except Exception:
        try:
            import pytz
            return pytz.timezone(IST_NAME)
        except Exception:
            return _UTC


IST = _tz()


def now_ist() -> datetime:
    """Current time as an aware IST datetime."""
    return datetime.now(IST)


def ist(dt: Optional[datetime], assume: str = "IST") -> datetime:
    """Return an aware IST datetime.

    A naive datetime is interpreted in `assume` (default IST, because every
    timestamp in this system originates from NSE/Angel in IST). Passing
    assume="UTC" makes that explicit when a UTC source is known.
    """
    if dt is None:
        return now_ist()
    if dt.tzinfo is not None:
        return dt.astimezone(IST)
    tz = _UTC if assume.upper() == "UTC" else IST
    return dt.replace(tzinfo=tz).astimezone(IST)


def to_utc(dt: datetime) -> datetime:
    """Aware UTC, for storage and cross-zone comparison."""
    return ist(dt).astimezone(_UTC)


def parse_expiry(value) -> Optional[datetime]:
    """Parse an exchange expiry into an aware IST datetime at session close.

    Accepts the formats the project actually sees:
      "29SEP2026"  (scrip master / option chain)
      "29-SEP-2026", "2026-09-29" (NSE CSV style)
      an already-parsed date or datetime

    Returns None when the value cannot be parsed. Callers must treat None as
    "expiry unknown" and refuse to compute a days-to-expiry from it, rather
    than defaulting to a guess.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _session_close(value.date())
    if isinstance(value, date):
        return _session_close(value)
    text = str(value).strip()
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%Y-%m-%d", "%d%B%Y", "%d-%m-%Y"):
        try:
            return _session_close(datetime.strptime(text, fmt).date())
        except ValueError:
            continue
    return None


def _session_close(d: date) -> datetime:
    """Expiry is the IST close of that trading session (15:30)."""
    return datetime.combine(d, time(15, 30), tzinfo=IST)


def session_close(now: Optional[datetime] = None) -> datetime:
    """IST market close (15:30) on the session containing `now`."""
    n = ist(now)
    return datetime.combine(n.date(), time(15, 30), tzinfo=IST)


def seconds_to_expiry(expiry, now: Optional[datetime] = None) -> Optional[float]:
    """Seconds until expiry. None when expiry is unknown (never a guess)."""
    exp = parse_expiry(expiry)
    if exp is None:
        return None
    return (exp - ist(now)).total_seconds()


def years_to_expiry(expiry, now: Optional[datetime] = None) -> Optional[float]:
    """Fractional years to expiry, for Black-Scholes. None if unknown/past.

    Same day -> the remaining intraday time to the close, which is what makes
    expiry-day greeks decay correctly instead of snapping to a whole day.
    """
    secs = seconds_to_expiry(expiry, now)
    if secs is None or secs <= 0:
        return None
    return secs / (365.0 * 24.0 * 3600.0)


def days_to_expiry(expiry, now: Optional[datetime] = None) -> Optional[int]:
    """Whole days to expiry, rounded up. None when expiry is unknown."""
    secs = seconds_to_expiry(expiry, now)
    if secs is None or secs <= 0:
        return 0 if secs == 0 else None
    return int(timedelta(seconds=secs).days) + (0 if secs % 86400 == 0 else 1)


def age_seconds(ts, now: Optional[datetime] = None) -> Optional[float]:
    """Age of a timestamp in seconds. None when ts is missing/unparsable.

    Accepts ISO strings, epoch seconds, epoch milliseconds and datetimes.
    An unparsable value returns None so the caller can fail closed instead of
    assuming the data is fresh.
    """
    dt = parse_timestamp(ts)
    if dt is None:
        return None
    return (ist(now) - dt).total_seconds()


def parse_timestamp(ts) -> Optional[datetime]:
    """Parse any supported timestamp into an aware IST datetime."""
    if ts is None or ts == "":
        return None
    if isinstance(ts, datetime):
        return ist(ts)
    if isinstance(ts, (int, float)):
        seconds = ts / 1000.0 if ts > 1e12 else float(ts)
        try:
            return datetime.fromtimestamp(seconds, IST)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(ts).strip()
    try:
        return ist(datetime.fromisoformat(text))
    except ValueError:
        pass
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return parse_timestamp(value)


def humanize_age(seconds: Optional[float]) -> str:
    """Short age string for the dashboard. 'Unavailable' when unknown."""
    if seconds is None:
        return "Unavailable"
    if seconds < 0:
        return f"{-seconds:.0f}s ahead"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


__all__ = [
    "IST", "now_ist", "ist", "to_utc", "parse_expiry", "session_close",
    "seconds_to_expiry", "years_to_expiry", "days_to_expiry",
    "age_seconds", "parse_timestamp", "humanize_age",
]
