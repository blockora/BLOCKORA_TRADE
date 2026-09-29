"""BLOCKORA_TRADE v3 — feature engine (Phase 2).

Builds a per-strike FeatureVector from underlying candles + option chain.
Indicators are computed only on CLOSED candles; missing inputs stay None and
are recorded in data_quality_flags.
"""
from __future__ import annotations

from typing import Any

from core.models import Candle, FeatureVector, OptionQuote, UnderlyingTick
from pipeline import indicators as ind
from pipeline.greeks import bs_greeks, dte_to_years


def build_features(
    tick: UnderlyingTick,
    candles_5m: list[Candle],
    quotes: list[OptionQuote],
    atm: float,
    dte_days: float,
    iv_history: list[float] | None = None,
) -> list[FeatureVector]:
    """iv_history: recent IV observations for a crude IV rank (None if absent)."""
    spot = tick.ltp
    flags: dict[str, str] = {}
    if spot is None:
        return []

    closes = [c.close for c in candles_5m]
    ema20 = ind.ema(closes, 20)
    ema50 = ind.ema(closes, 50)
    ema200 = ind.ema(closes, 200)
    rsi14 = ind.rsi(closes, 14)
    atr14 = ind.atr(candles_5m, 14)
    adx14 = ind.adx(candles_5m, 14)
    vwap_v = ind.vwap(candles_5m[-75:]) if candles_5m else None
    roc5 = ind.momentum_roc(closes, 5)

    for name, val in (("ema200", ema200), ("vwap", vwap_v), ("atr", atr14),
                      ("adx", adx14), ("rsi", rsi14)):
        if val is None:
            flags[f"missing_{name}"] = "UNAVAILABLE"

    ema_stack = None
    if ema20 and ema50:
        ema_stack = "BULLISH" if ema20 > ema50 else ("BEARISH" if ema20 < ema50 else "FLAT")
    vwap_rel = None
    if vwap_v and candles_5m:
        vwap_rel = "ABOVE" if closes[-1] > vwap_v else "BELOW"

    iv_lo = min(iv_history) if iv_history else None
    iv_hi = max(iv_history) if iv_history else None

    out: list[FeatureVector] = []
    T = dte_to_years(dte_days)
    for q in quotes:
        iv = q.iv
        iv_rank = None
        if iv and iv_history and iv_hi is not None and iv_hi > iv_lo:
            iv_rank = (iv - iv_lo) / (iv_hi - iv_lo) * 100.0
        greeks = bs_greeks(spot, q.strike, (iv / 100.0) if iv else 0.12, T,
                           option_type=q.option_type)
        fv = FeatureVector(
            strike=q.strike, option_type=q.option_type, expiry=q.expiry,
            distance_atm=q.strike - atm,
            ltp=q.ltp, volume=q.volume, oi=q.oi, change_oi=q.change_oi,
            bid=q.bid, ask=q.ask, spread_pct=q.spread_pct, iv=iv, iv_rank=iv_rank,
            delta=greeks["delta"], gamma=greeks["gamma"],
            theta=greeks["theta"], vega=greeks["vega"],
            underlying_price=spot,
            momentum_5m=roc5,
            trend_flag=ema_stack,
            vwap_rel=vwap_rel,
            ema_rel=("ABOVE" if ema20 and closes[-1] > ema20 else
                     "BELOW" if ema20 else None),
            market_structure=("TRENDING" if adx14 and adx14 > 20 else
                              "RANGE" if adx14 is not None else None),
            volatility_state=("HIGH" if atr14 and spot and (atr14 / spot * 100) > 0.35
                              else "NORMAL" if atr14 else None),
            data_quality_flags={**flags},
        )
        # attach quote provenance
        fv.data_quality_flags["quote_quality_status"] = q.quality.status.value
        if q.quality.reason:
            fv.data_quality_flags["quote_quality_reason"] = q.quality.reason
        out.append(fv)
    return out
