"""BLOCKORA_TRADE v3 — pure indicator functions on Candle lists.

All functions take CLOSED candles only (oldest first) and return floats.
No look-ahead is possible: callers pass only bars closed at decision time.
"""
from __future__ import annotations

from core.models import Candle


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def true_ranges(candles: list[Candle]) -> list[float]:
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c.high - c.low)
            continue
        pc = candles[i - 1].close
        trs.append(max(c.high - c.low, abs(c.high - pc), abs(c.low - pc)))
    return trs


def atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period:
        return None
    trs = true_ranges(candles)
    return sum(trs[-period:]) / period


def vwap(candles: list[Candle]) -> float | None:
    """Session VWAP over the provided (session) candles."""
    if not candles:
        return None
    pv = sum((c.high + c.low + c.close) / 3.0 * (c.volume or 1) for c in candles)
    v = sum((c.volume or 1) for c in candles)
    return pv / v if v else None


def adx(candles: list[Candle], period: int = 14) -> float | None:
    """Simplified Wilder ADX (trend strength, direction-agnostic)."""
    n = len(candles)
    if n < 2 * period + 1:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        c, pc = candles[i], candles[i - 1]
        up, dn = c.high - pc.high, pc.low - c.low
        pdm = up if (up > dn and up > 0) else 0.0
        mdm = dn if (dn > up and dn > 0) else 0.0
        trs.append(max(c.high - c.low, abs(c.high - pc.close), abs(c.low - pc.close)))
        plus_dm.append(pdm)
        minus_dm.append(mdm)
    atr_ = sum(trs[:period]) / period
    pdi = 100.0 * (sum(plus_dm[:period]) / period) / atr_ if atr_ else 0.0
    mdi = 100.0 * (sum(minus_dm[:period]) / period) / atr_ if atr_ else 0.0
    dxs = []
    for i in range(period, len(trs)):
        atr_ = (atr_ * (period - 1) + trs[i]) / period
        pdi = 100.0 * ((pdi * (period - 1) / 100.0 * atr_ + plus_dm[i]) / period) / atr_ \
            if atr_ else pdi
        mdi = 100.0 * ((mdi * (period - 1) / 100.0 * atr_ + minus_dm[i]) / period) / atr_ \
            if atr_ else mdi
        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0
        dxs.append(dx)
    if not dxs:
        return None
    return sum(dxs[-period:]) / period


def momentum_roc(values: list[float], lookback: int = 5) -> float | None:
    """Rate of change in percent over the last `lookback` closes."""
    if len(values) < lookback + 1 or values[-lookback - 1] == 0:
        return None
    return (values[-1] - values[-lookback - 1]) / values[-lookback - 1] * 100.0
