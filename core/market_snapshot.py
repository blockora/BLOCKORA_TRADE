"""One authoritative market snapshot per analysis cycle.

Live defects this fixes
-----------------------
1. NIFTY spot repeated at 22683.75 for five consecutive cycles while the
   exchange showed ~22704. get_live_data() falls back to a cached block on
   error and stamps it with datetime.now(), so a stale price was presented
   as a fresh quote and the freshness guard saw age 0.

2. Ranking printed "ATR 12.5" on every cycle. That was not a calculation at
   all: StrikeRankingEngine read market_data.get("atr", 12.5) and nothing
   ever wrote an "atr" key into market_data, so the hardcoded default was
   used forever, while the dashboard showed the real 5-minute ATR (21.7,
   then 54.1). One generic name, two different meanings.

3. Spot, OHLC, RSI, ADX, ATR and VWAP were assembled from different objects
   at different moments, so a snapshot could read spot 22683.75 with an
   OHLC close of 22780.25.

This module builds the snapshot ONCE per cycle, from one market_data dict
and one option chain, and stamps every field with where it came from and
how old it is. Ranking, the dashboard, the invalidation level and the
persisted diagnostics all read this one object, so they cannot disagree.

Nothing here invents a value: an unknown input produces None plus an
explicit reason, never a default.
"""
from __future__ import annotations

from typing import Any, Optional

from core.timeutil import age_seconds, humanize_age, ist, parse_timestamp

#: Underlying/option quote older than this is stale. Configurable via
#: freshness.spot_max_age_seconds; the default matches the existing guard.
DEFAULT_SPOT_MAX_AGE_SEC = 60.0

#: Timeframe of the primary candle series and therefore of ATR/RSI/ADX.
#: The broker feeds FIVE_MINUTE candles, so these are 5-minute values.
PRIMARY_TIMEFRAME = "5m"


class MarketSnapshot:
    """Immutable-ish view of everything measured at one instant.

    Attribute access is intentionally explicit rather than a dict so a typo
    in the dashboard fails loudly instead of printing an empty string.
    """

    __slots__ = (
        "spot", "spot_timestamp", "spot_age_sec", "spot_source",
        "open", "high", "low", "close", "candle_timeframe",
        "rsi", "adx", "atr", "macd_hist", "indicator_timeframe",
        "vwap", "support", "resistance", "bias", "expected_move",
        "regime", "vix", "pcr", "max_pain",
        "chain_timestamp", "chain_age_sec", "chain_source",
        "expiry", "multi_timeframe", "data_status", "stale_reasons",
        "_raw",
    )

    def __init__(self, **kw: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, kw.get(name))
        if self.stale_reasons is None:
            self.stale_reasons = []
        if self.data_status is None:
            self.data_status = "UNKNOWN"

    # ------------------------------------------------------------------
    def is_spot_fresh(self, max_age: float = DEFAULT_SPOT_MAX_AGE_SEC) -> bool:
        if self.spot is None or self.spot <= 0:
            return False
        if self.spot_age_sec is None:
            # No timestamp we can trust -> cannot be proven fresh.
            return False
        return self.spot_age_sec <= max_age

    def is_chain_fresh(self, max_age: float = DEFAULT_SPOT_MAX_AGE_SEC) -> bool:
        if self.chain_timestamp is None:
            return False
        if self.chain_age_sec is None:
            return False
        return self.chain_age_sec <= max_age

    @property
    def staleness_reasons(self) -> list:
        """Human reasons this snapshot must not drive a trade."""
        out = list(self.stale_reasons or [])
        if not self.is_spot_fresh():
            if self.spot is None or self.spot <= 0:
                out.append("stale_market_data:spot_missing")
            elif self.spot_age_sec is None:
                out.append("stale_market_data:spot_timestamp_unknown")
            else:
                out.append(
                    f"stale_market_data:spot_age_{self.spot_age_sec:.0f}s")
        if self.chain_timestamp is not None and not self.is_chain_fresh():
            if self.chain_age_sec is None:
                out.append("stale_market_data:chain_timestamp_unknown")
            else:
                out.append(f"stale_market_data:chain_age_{self.chain_age_sec:.0f}s")
        return out

    @property
    def tradable(self) -> bool:
        return not self.staleness_reasons

    def spot_age_display(self) -> str:
        return humanize_age(self.spot_age_sec)

    def chain_age_display(self) -> str:
        return humanize_age(self.chain_age_sec)

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__slots__
                if name != "_raw"}


def _f(value, default=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out


def build_market_snapshot(market_data: dict, option_chain: dict,
                          analysis_results: dict, regime: dict,
                          vix=None, now=None,
                          max_age: float = DEFAULT_SPOT_MAX_AGE_SEC) -> MarketSnapshot:
    """Assemble the single snapshot every downstream consumer must read.

    `now` is an aware IST datetime (core.timeutil.now_ist). Passing it
    explicitly keeps the function testable and keeps one clock reading per
    cycle instead of several that can straddle a second boundary.
    """
    md = market_data or {}
    ch = option_chain or {}
    ar = analysis_results or {}

    indicators = ar.get("indicators") or {}
    ctx = ar.get("trade_context") or {}
    sr = ar.get("support_resistance") or {}
    oi = ar.get("oi_analysis") or {}
    mtf = ar.get("multi_timeframe") or {}

    spot = _f(md.get("ltp"))
    spot_ts_raw = md.get("quote_timestamp") or md.get("timestamp")
    spot_dt = parse_timestamp(spot_ts_raw)
    spot_age = age_seconds(spot_dt, now) if spot_dt else None

    chain_dt = parse_timestamp(ch.get("timestamp"))
    chain_age = age_seconds(chain_dt, now) if chain_dt else None

    # data_source must reflect reality: CACHED means the value is reused
    spot_source = str(md.get("data_source") or "UNKNOWN")

    atr = _f(indicators.get("atr"))
    rsi = _f(indicators.get("rsi"))
    adx = _f(indicators.get("adx"))

    snap = MarketSnapshot(
        spot=spot,
        spot_timestamp=spot_dt,
        spot_age_sec=spot_age,
        spot_source=spot_source,
        open=_f(md.get("open")),
        high=_f(md.get("high")),
        low=_f(md.get("low")),
        close=_f(md.get("close")),
        candle_timeframe=PRIMARY_TIMEFRAME,
        rsi=rsi,
        adx=adx,
        atr=atr,
        macd_hist=_f(indicators.get("macd_hist")),
        indicator_timeframe=PRIMARY_TIMEFRAME,
        vwap=_f(ctx.get("vwap")),
        support=_f(sr.get("support")),
        resistance=_f(sr.get("resistance")),
        bias=(ar.get("trend") or {}).get("direction") or ctx.get("direction"),
        expected_move=_f(ctx.get("expected_move")),
        regime=regime or {},
        vix=_f(vix),
        pcr=_f(oi.get("pcr"), ch.get("pcr")),
        max_pain=_f(ch.get("max_pain")),
        chain_timestamp=chain_dt,
        chain_age_sec=chain_age,
        chain_source=str(ch.get("source") or "UNKNOWN"),
        expiry=ch.get("expiry") or ctx.get("expiry_date"),
        multi_timeframe=mtf,
        data_status="FRESH" if (spot_age is not None
                                and spot_age <= max_age
                                and spot_source != "CACHED")
                      else ("CACHED" if spot_source == "CACHED" else "STALE"),
        _raw={"market_data": md, "chain": ch, "analysis": ar},
    )
    return snap
