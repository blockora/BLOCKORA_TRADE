"""BLOCKORA_TRADE v3 — market regime engine (Phase 3).

Classifies HTF (regime), MTF (trend), LTF (execution) from candles and
resolves conflicts per docs/FILTERS.md section 5:
  HTF+MTF aligned with counter-LTF  -> PULLBACK (tradeable)
  MTF against HTF                   -> TREND_CONFLICT (no trade)
  MTF structure break vs HTF        -> REVERSAL_RISK (no trade)
  flat/mixed everywhere             -> UNCERTAIN
"""
from __future__ import annotations

from dataclasses import dataclass

from core.models import Candle, Direction
from pipeline import indicators as ind


@dataclass
class Regime:
    htf: Direction
    mtf: Direction
    ltf: Direction
    classification: str          # ALIGNED / PULLBACK / WEAK_ALIGNMENT / TREND_CONFLICT / REVERSAL_RISK / UNCERTAIN
    adx_15m: float | None = None
    notes: list[str] = None      # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.notes is None:
            self.notes = []

    @property
    def market_bias(self) -> Direction:
        return self.htf if self.htf != Direction.RANGE else self.mtf


def _tf_direction(candles: list[Candle]) -> tuple[Direction, float | None]:
    """Direction of one timeframe from EMA20/50 stack + slope."""
    if len(candles) < 55:
        return Direction.UNCERTAIN, None
    closes = [c.close for c in candles]
    e20, e50 = ind.ema(closes, 20), ind.ema(closes, 50)
    adx_v = ind.adx(candles, 14)
    if e20 is None or e50 is None:
        return Direction.UNCERTAIN, adx_v
    if e20 > e50 * 1.0002:
        d = Direction.BULLISH
    elif e20 < e50 * 0.9998:
        d = Direction.BEARISH
    else:
        d = Direction.RANGE
    if adx_v is not None and adx_v < 12:
        d = Direction.RANGE
    return d, adx_v


def classify(candles_1h: list[Candle], candles_15m: list[Candle],
             candles_5m: list[Candle]) -> Regime:
    htf, _ = _tf_direction(candles_1h)
    mtf, adx_15 = _tf_direction(candles_15m)
    # LTF window must contain >= _tf_direction's minimum bars (55); use the
    # most recent 60 bars of the 5m series (= 5 hours of context).
    ltf, _ = _tf_direction(candles_5m[-60:])

    notes: list[str] = []
    if Direction.UNCERTAIN in (htf, mtf, ltf):
        return Regime(htf, mtf, ltf, "UNCERTAIN", adx_15,
                      notes + ["insufficient or unclear data on a timeframe"])

    if htf == mtf == ltf and htf != Direction.RANGE:
        return Regime(htf, mtf, ltf, "ALIGNED", adx_15, notes)

    if htf == mtf and htf != Direction.RANGE and ltf != htf:
        # counter-LTF inside aligned HTF/MTF = pullback (timing, not conflict)
        notes.append("LTF counter-move treated as pullback, not reversal")
        return Regime(htf, mtf, ltf, "PULLBACK", adx_15, notes)

    if htf == mtf and htf != Direction.RANGE:
        return Regime(htf, mtf, ltf, "ALIGNED", adx_15, notes)

    if htf != Direction.RANGE and mtf == Direction.RANGE:
        return Regime(htf, mtf, ltf, "WEAK_ALIGNMENT", adx_15,
                      notes + ["HTF trend, MTF flat — needs larger margin"])

    if htf != Direction.RANGE and mtf != htf and mtf != Direction.RANGE:
        return Regime(htf, mtf, ltf, "TREND_CONFLICT", adx_15,
                      notes + ["MTF runs against HTF"])

    return Regime(htf, mtf, ltf, "UNCERTAIN", adx_15, notes + ["mixed/flat timeframes"])
