"""Tests: IST session logic."""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.session import IST, is_market_open, now_ist, utc_iso


def test_market_open_during_hours():
    t = datetime(2026, 9, 28, 10, 0, tzinfo=IST)  # Monday
    assert is_market_open(t) is True


def test_market_closed_before_and_after():
    assert is_market_open(datetime(2026, 9, 28, 9, 0, tzinfo=IST)) is False
    assert is_market_open(datetime(2026, 9, 28, 15, 45, tzinfo=IST)) is False


def test_weekend_closed():
    sat = datetime(2026, 10, 3, 11, 0, tzinfo=IST)
    sun = datetime(2026, 10, 4, 11, 0, tzinfo=IST)
    assert is_market_open(sat) is False
    assert is_market_open(sun) is False


def test_boundary_inclusive():
    assert is_market_open(datetime(2026, 9, 28, 9, 15, tzinfo=IST)) is True
    assert is_market_open(datetime(2026, 9, 28, 15, 30, tzinfo=IST)) is True


def test_naive_datetime_treated_as_ist():
    naive = datetime(2026, 9, 28, 10, 0)
    assert is_market_open(naive) is True


def test_utc_conversion():
    ist_dt = datetime(2026, 9, 28, 15, 30, tzinfo=IST)
    assert utc_iso(ist_dt) == "2026-09-28T10:00:00Z"


def test_now_ist_zone():
    assert now_ist().tzinfo is not None
